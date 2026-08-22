import { createContext, useContext, useState, useCallback } from "react";

export interface PreviewFile {
  path: string;
  filename: string;
  kind: "md" | "html";
  sessionId?: string | null;
}

interface PreviewContextValue {
  file: PreviewFile | null;
  open: (file: PreviewFile) => void;
  close: () => void;
}

const PreviewContext = createContext<PreviewContextValue>({
  file: null,
  open: () => {},
  close: () => {},
});

export function PreviewProvider({ children }: { children: React.ReactNode }) {
  const [file, setFile] = useState<PreviewFile | null>(null);

  const open = useCallback((f: PreviewFile) => setFile(f), []);
  const close = useCallback(() => setFile(null), []);

  return (
    <PreviewContext.Provider value={{ file, open, close }}>
      {children}
    </PreviewContext.Provider>
  );
}

export function usePreview() {
  return useContext(PreviewContext);
}
