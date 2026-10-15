/// <reference types="vite/client" />

declare module "*.json?raw" {
  const source: string;
  export default source;
}
