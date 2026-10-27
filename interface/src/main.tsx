import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles/tokens.css";
import "./styles/shell.css";
import "./styles/case-list.css";
import "./styles/create-case.css";
import "./styles/overview.css";
import "./styles/evidence-intake.css";
import "./styles/register.css";
import "./styles/evidence-viewer.css";
import "./styles/search.css";
import "./styles/timeline.css";
import "./styles/administration.css";
import "./styles/confirm-dialog.css";
import "./styles/audit-exports.css";
import "./styles/markdown.css";
import "./styles/saul-summary.css";
import "./styles/email-intake.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
