// Backend API Configuration
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const config = {
  apiBaseUrl: API_BASE_URL,
  appName: import.meta.env.VITE_APP_NAME || "Safai",
};

export default config;
