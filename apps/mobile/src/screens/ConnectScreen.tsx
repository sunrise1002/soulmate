import { useState } from "react";
import { ActivityIndicator, Button, Text, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import type { DeviceConnection } from "@soulmate/sdk";

import { pairWithScannedCode } from "../pairing.ts";
import { styles } from "../theme.ts";

interface Props {
  deviceName: string;
  onPaired: (connection: DeviceConnection) => void;
}

export function ConnectScreen({ deviceName, onPaired }: Props) {
  const [permission, requestPermission] = useCameraPermissions();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const handleScan = async (scanned: string) => {
    if (pending) {
      return;
    }
    setPending(true);
    setError(null);
    try {
      onPaired(
        await pairWithScannedCode({
          scanned,
          deviceName,
          platform: "mobile",
          now: new Date(),
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Pairing failed.");
    } finally {
      setPending(false);
    }
  };

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Connect</Text>
      <Text style={styles.hint}>
        On your computer, open Soulmate, enable access from other devices, and
        scan the pairing code. Your Personal Model never leaves that computer.
      </Text>
      {permission?.granted !== true ? (
        <Button
          title="Allow camera to scan the code"
          onPress={() => void requestPermission()}
        />
      ) : (
        <View style={styles.camera}>
          <CameraView
            style={{ flex: 1 }}
            barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
            onBarcodeScanned={(event) => void handleScan(event.data)}
          />
        </View>
      )}
      {pending && <ActivityIndicator accessibilityLabel="Pairing" />}
      {error !== null && <Text style={styles.error}>{error}</Text>}
    </View>
  );
}
