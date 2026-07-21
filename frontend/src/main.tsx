import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import CustomerCheckout from "./components/CustomerCheckout";
import "./styles.css";

// The customer-facing checkout page (opened via the QR / SMS link on the
// customer's phone) lives at /checkout/{id}; everything else is the rep app.
const checkoutMatch = window.location.pathname.match(/^\/checkout\/([\w-]+)\/?$/);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {checkoutMatch ? <CustomerCheckout id={checkoutMatch[1]} /> : <App />}
  </React.StrictMode>
);
