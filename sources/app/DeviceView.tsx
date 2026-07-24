import * as React from 'react';
import { ActivityIndicator, Image, ScrollView, Text, TextInput, View } from 'react-native';
import { rotateImage } from '../modules/imaging';
import { toBase64Image } from '../utils/base64';
import { Agent } from '../agent/Agent';
import { InvalidateSync } from '../utils/invalidateSync';
import { textToSpeech } from '../modules/openai';

function usePhotos(device: BluetoothRemoteGATTServer) {

    // Subscribe to device
    const [photos, setPhotos] = React.useState<Uint8Array[]>([]);
    const [subscribed, setSubscribed] = React.useState<boolean>(false);
    React.useEffect(() => {
        (async () => {

            // 缓冲桶模式：把所有收到的包存进 Map，收到结束标记后拼装
            const CHUNK_SIZE = 200; // 固件端每个 chunk 最多 200 字节
            let chunkMap = new Map<number, Uint8Array>();
            let maxChunkId = 0;

            function assemblePhoto() {
                if (chunkMap.size === 0) return;

                // 按包序号排序
                const sortedIds = Array.from(chunkMap.keys()).sort((a, b) => a - b);

                // 检测缺包
                const gaps: number[] = [];
                for (let i = 0; i < sortedIds.length - 1; i++) {
                    if (sortedIds[i + 1] - sortedIds[i] > 1) {
                        for (let g = sortedIds[i] + 1; g < sortedIds[i + 1]; g++) {
                            gaps.push(g);
                        }
                    }
                }
                if (gaps.length > 0) {
                    console.warn('Missing chunks:', gaps.length, 'IDs:', gaps.slice(0, 10), gaps.length > 10 ? '...' : '');
                }

                // 按 chunk ID 计算正确的字节偏移来拼接
                // 每个 chunk 在原 JPEG 中的位置 = chunkId * CHUNK_SIZE
                // 最后一个 chunk 可能小于 CHUNK_SIZE
                const lastId = sortedIds[sortedIds.length - 1];
                const estimatedTotalSize = lastId * CHUNK_SIZE + chunkMap.get(lastId)!.length;
                const fullBuffer = new Uint8Array(estimatedTotalSize);

                for (const id of sortedIds) {
                    const chunk = chunkMap.get(id)!;
                    const byteOffset = id * CHUNK_SIZE;
                    fullBuffer.set(chunk, byteOffset);
                }

                console.log('Photo assembled:', fullBuffer.length, 'bytes,', chunkMap.size, 'chunks,', gaps.length, 'gaps');
                chunkMap.clear();
                maxChunkId = 0;

                // 打印 JPEG 文件头信息，用于诊断
                console.log('JPEG header:', Array.from(fullBuffer.slice(0, 8)).map(b => '0x' + b.toString(16).padStart(2, '0')).join(' '));

                // 🔧 临时：不做旋转，直接显示原图（上箭头观察原始摄像头数据）
                setPhotos((p) => [...p, fullBuffer]);
            }

            // Subscribe for photo updates
            const service = await device.getPrimaryService('19B10000-E8F2-537E-4F6C-D104768A1214'.toLowerCase());
            const photoCharacteristic = await service.getCharacteristic('19b10005-e8f2-537e-4f6c-d104768a1214');
            await photoCharacteristic.startNotifications();
            setSubscribed(true);
            photoCharacteristic.addEventListener('characteristicvaluechanged', (e) => {
                let value = (e.target as BluetoothRemoteGATTCharacteristic).value!;
                // 必须用 byteOffset + byteLength，否则会读到 buffer 中的脏数据
                let array = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
                if (array[0] == 0xff && array[1] == 0xff) {
                    // 结束标记 → 拼装照片
                    assemblePhoto();
                } else {
                    let packetId = array[0] + (array[1] << 8);
                    let packet = array.slice(2);
                    // 收到 chunk 0 且有旧数据 → 上一张照片的结束标记丢了，先拼装旧照片
                    if (packetId === 0 && chunkMap.size > 0) {
                        console.log('New photo detected, assembling previous');
                        assemblePhoto();
                    }
                    // 直接存入 Map，不检查顺序
                    chunkMap.set(packetId, packet);
                }
            });
            // Start automatic photo capture every 5s
            const photoControlCharacteristic = await service.getCharacteristic('19b10006-e8f2-537e-4f6c-d104768a1214');
            await photoControlCharacteristic.writeValue(new Uint8Array([0x05]));
        })();
    }, []);

    return [subscribed, photos] as const;
}

export const DeviceView = React.memo((props: { device: BluetoothRemoteGATTServer }) => {
    const [subscribed, photos] = usePhotos(props.device);
    const agent = React.useMemo(() => new Agent(), []);
    const agentState = agent.use();

    // Background processing agent
    const processedPhotos = React.useRef<Uint8Array[]>([]);
    const sync = React.useMemo(() => {
        let processed = 0;
        return new InvalidateSync(async () => {
            if (processedPhotos.current.length > processed) {
                let unprocessed = processedPhotos.current.slice(processed);
                processed = processedPhotos.current.length;
                await agent.addPhoto(unprocessed);
            }
        });
    }, []);
    React.useEffect(() => {
        processedPhotos.current = photos;
        sync.invalidate();
    }, [photos]);

    React.useEffect(() => {
        if (agentState.answer) {
            textToSpeech(agentState.answer)
        }
    }, [agentState.answer])

    return (
        <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
            <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
                    {photos.map((photo, index) => (
                        <Image key={index} style={{ width: 100, height: 100 }} source={{ uri: toBase64Image(photo) }} />
                    ))}
                </View>
            </View>

            <View style={{ backgroundColor: 'rgb(28 28 28)', height: 600, width: 600, borderRadius: 64, flexDirection: 'column', padding: 64 }}>
                <View style={{ flexGrow: 1, justifyContent: 'center', alignItems: 'center' }}>
                    {agentState.loading && (<ActivityIndicator size="large" color={"white"} />)}
                    {agentState.answer && !agentState.loading && (<ScrollView style={{ flexGrow: 1, flexBasis: 0 }}><Text style={{ color: 'white', fontSize: 32 }}>{agentState.answer}</Text></ScrollView>)}
                </View>
                <TextInput
                    style={{ color: 'white', height: 64, fontSize: 32, borderRadius: 16, backgroundColor: 'rgb(48 48 48)', padding: 16 }}
                    placeholder='What do you need?'
                    placeholderTextColor={'#888'}
                    readOnly={agentState.loading}
                    onSubmitEditing={(e) => agent.answer(e.nativeEvent.text)}
                />
            </View>
        </View>
    );
});