declare module '@novnc/novnc' {
  export default class RFB {
    constructor(target: HTMLElement, url: string, options?: Record<string, unknown>);
    scaleViewport: boolean;
    resizeSession: boolean;
    background: string;
    showDotCursor: boolean;
    viewOnly: boolean;
    clipViewport: boolean;
    focusOnClick: boolean;
    disconnect(): void;
    sendCredentials(credentials: { password: string }): void;
    sendCtrlAltDel(): void;
    sendKey(keysym: number, code: string, down?: boolean): void;
    machineShutdown(): void;
    addEventListener(type: string, listener: (e: any) => void): void;
    removeEventListener(type: string, listener: (e: any) => void): void;
  }
}
