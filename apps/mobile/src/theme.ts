import { StyleSheet } from "react-native";

export const styles = StyleSheet.create({
  screen: { flex: 1, padding: 16, gap: 12 },
  title: { fontSize: 22, fontWeight: "600" },
  hint: { fontSize: 14, opacity: 0.7 },
  error: { color: "#b3261e" },
  input: {
    borderWidth: 1,
    borderColor: "#8a8a8a",
    borderRadius: 6,
    padding: 10,
    fontSize: 16,
  },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  card: {
    borderWidth: 1,
    borderColor: "#d0d0d0",
    borderRadius: 8,
    padding: 12,
    gap: 4,
  },
  tabs: { flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 12 },
  camera: { height: 280, borderRadius: 8, overflow: "hidden" },
});
