#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QWebSocketServer>
#include <QWebSocket>
#include <QProcess>
#include <QMap>
#include <QByteArray>

class QLabel;
class QPushButton;
class QTextEdit;

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    MainWindow(QWidget *parent = nullptr);
    ~MainWindow();

private slots:
    void onNewConnection();
    void onBinaryMessage(const QByteArray &message);
    void onClientDisconnected();
    void onScreenshot();

private:
    void startBridge();

    // UI
    QLabel *m_photoLabel;
    QTextEdit *m_logText;
    QLabel *m_statusLabel;
    QPushButton *m_screenshotBtn;
    QLabel *m_countLabel;

    // 保存最新 JPEG 用于截图
    QByteArray m_lastJpeg;
    int m_photoCount = 0;

    // WebSocket 服务器
    QWebSocketServer *m_server;
    QWebSocket *m_client = nullptr;

    // BLE 桥接进程
    QProcess *m_bridgeProcess = nullptr;
};

#endif // MAINWINDOW_H
