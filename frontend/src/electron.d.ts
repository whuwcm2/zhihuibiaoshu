export {}

declare global {
  interface Window {
    electronAPI?: {
      showItemInFolder: (target: string) => Promise<void>
      openPath: (target: string) => Promise<string>
    }
  }
}
