import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppStoreProvider } from "@/state/AppStore";
import "./styles/global.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root element is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <AppStoreProvider>
      <App />
    </AppStoreProvider>
  </StrictMode>,
);
