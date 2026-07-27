#include "mainwindow.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QTextEdit>
#include <QPixmap>
#include <QDateTime>
#include <QFile>
#include <QDir>
#include <QCoreApplication>
#include <QMessageBox>
#include <QBuffer>
#include <QTransform>
#include <QDebug>

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    setWindowTitle("QtGlass - AI 智能眼镜桌面客户端");
    resize(900, 650);

    auto *central = new QWidget;
    auto *mainLayout = new QVBoxLayout(central);

    // 状态栏
    m_statusLabel = new QLabel("Waiting for browser...");
    m_statusLabel->setAlignment(Qt::AlignCenter);
    m_statusLabel->setStyleSheet("background: #333; color: #0f0; padding: 8px; font-size: 16px;");

    // 照片显示区
    m_photoLabel = new QLabel("No photo yet");
    m_photoLabel->setMinimumSize(600, 400);
    m_photoLabel->setAlignment(Qt::AlignCenter);
    m_photoLabel->setStyleSheet("background: #1a1a1a; border: 2px dashed #444; color: #888; font-size: 20px;");

    // 日志
    m_logText = new QTextEdit;
    m_logText->setReadOnly(true);
    m_logText->setMaximumHeight(150);

    mainLayout->addWidget(m_statusLabel);
    mainLayout->addWidget(m_photoLabel);

    // 按钮栏
    auto *btnBar = new QHBoxLayout;
    m_screenshotBtn = new QPushButton("📸 截图保存");
    m_screenshotBtn->setStyleSheet("QPushButton { background: #0078D4; color: white; padding: 8px 20px; border-radius: 6px; font-size: 14px; } QPushButton:hover { background: #1084E0; }");
    m_countLabel = new QLabel("已接收: 0 张");
    m_countLabel->setStyleSheet("color: #aaa; font-size: 13px;");
    btnBar->addWidget(m_screenshotBtn);
    btnBar->addStretch();
    btnBar->addWidget(m_countLabel);
    mainLayout->addLayout(btnBar);

    mainLayout->addWidget(new QLabel("Log:"));
    mainLayout->addWidget(m_logText);
    setCentralWidget(central);

    // WebSocket server
    m_server = new QWebSocketServer("QtGlass", QWebSocketServer::NonSecureMode, this);
    if (m_server->listen(QHostAddress::LocalHost, 9000)) {
        m_logText->append("WS Server started: ws://localhost:9000");
        m_statusLabel->setText("Starting BLE bridge...");
    } else {
        m_logText->append("ERROR: " + m_server->errorString());
        m_statusLabel->setText("Server start failed");
    }

    connect(m_server, &QWebSocketServer::newConnection,
            this, &MainWindow::onNewConnection);
    connect(m_screenshotBtn, &QPushButton::clicked,
            this, &MainWindow::onScreenshot);

    QDir().mkpath("photos");
    m_logText->append("Photo save dir: photos/");

    // 自动启动 BLE 桥接
    startBridge();
}

MainWindow::~MainWindow()
{
    if (m_bridgeProcess) {
        m_bridgeProcess->kill();
        m_bridgeProcess->waitForFinished(3000);
    }
    m_server->close();
}

void MainWindow::startBridge()
{
    m_bridgeProcess = new QProcess(this);

    // ble_bridge.py 放在 exe 同目录下
    QString scriptPath = QCoreApplication::applicationDirPath() + "/ble_bridge.py";
    // 开发时从项目目录找
    if (!QFile::exists(scriptPath)) {
        scriptPath = "D:/OpenGlass-main/QtGlassDemo/ble_bridge.py";
    }

    if (!QFile::exists(scriptPath)) {
        m_logText->append("ERROR: ble_bridge.py not found!");
        return;
    }

    m_logText->append("Starting BLE bridge...");
    m_bridgeProcess->setProcessChannelMode(QProcess::MergedChannels);
    m_bridgeProcess->start("python", QStringList() << scriptPath);

    connect(m_bridgeProcess, &QProcess::readyRead, this, [this]() {
        QString output = m_bridgeProcess->readAll();
        for (QString line : output.split('\n')) {
            line = line.trimmed();
            if (!line.isEmpty()) m_logText->append("[BLE] " + line);
        }
    });
}

void MainWindow::onNewConnection()
{
    if (m_client) {
        QWebSocket *rejected = m_server->nextPendingConnection();
        rejected->close();
        delete rejected;
        return;
    }

    m_client = m_server->nextPendingConnection();
    m_logText->append(QString("BLE bridge connected: %1").arg(m_client->peerAddress().toString()));

    connect(m_client, &QWebSocket::binaryMessageReceived,
            this, &MainWindow::onBinaryMessage);
    connect(m_client, &QWebSocket::disconnected,
            this, &MainWindow::onClientDisconnected);
    connect(m_client, &QWebSocket::textMessageReceived, this, [this](const QString &msg) {
        m_logText->append("MSG: " + msg);
    });

    m_statusLabel->setText("ESP32 connected - waiting for photos...");
}

void MainWindow::onBinaryMessage(const QByteArray &message)
{
    m_photoCount++;
    m_countLabel->setText(QString("已接收: %1 张").arg(m_photoCount));

    QPixmap pixmap;
    if (pixmap.loadFromData(message)) {
        // 旋转 270 度纠正摄像头方向
        QTransform transform;
        transform.rotate(270);
        pixmap = pixmap.transformed(transform);

        pixmap = pixmap.scaled(m_photoLabel->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation);

        // 把旋转后的图片重新编码为 JPEG 存起来，供截图使用
        QByteArray rotatedJpeg;
        QBuffer buffer(&rotatedJpeg);
        buffer.open(QIODevice::WriteOnly);
        pixmap.save(&buffer, "JPEG", 90);
        m_lastJpeg = rotatedJpeg;

        m_photoLabel->setPixmap(pixmap);
        m_photoLabel->setStyleSheet("background: #1a1a1a;");
        m_statusLabel->setText(QString("Live - %1 KB | 已存 %2 张")
            .arg(message.size() / 1024).arg(m_photoCount));
    } else {
        m_logText->append("JPEG decode failed");
    }
}

void MainWindow::onClientDisconnected()
{
    m_logText->append("BLE bridge disconnected");
    m_statusLabel->setText("BLE disconnected - waiting...");
    if (m_client) {
        m_client->deleteLater();
        m_client = nullptr;
    }
}

void MainWindow::onScreenshot()
{
    if (m_lastJpeg.isEmpty()) {
        QMessageBox::information(this, "截图", "还没有收到照片！");
        return;
    }

    QString filename = QString("photos/screenshot_%1.jpg")
        .arg(QDateTime::currentDateTime().toString("yyyyMMdd_HHmmss"));
    QFile file(filename);
    if (file.open(QIODevice::WriteOnly)) {
        file.write(m_lastJpeg);
        file.close();
        m_logText->append(QString("📸 Screenshot: %1").arg(filename));
        m_statusLabel->setText(QString("截图已保存: %1").arg(filename));
    }
}
