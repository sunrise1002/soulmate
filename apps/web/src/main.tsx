import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App.tsx";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("The web client root element is missing.");
}

createRoot(container).render(
  <StrictMode>
    <App origin={window.location.origin} storage={window.localStorage} />
  </StrictMode>,
);
