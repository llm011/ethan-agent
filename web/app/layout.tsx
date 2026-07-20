import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Ethan Agent",
  description: "Personal AI Agent",
  icons: {
    icon: [
      { url: "/icon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/icon-64.png", sizes: "64x64", type: "image/png" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: { url: "/apple-icon.png", sizes: "180x180", type: "image/png" },
    shortcut: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0" />
        <script
          dangerouslySetInnerHTML={{
            // 首帧 paint 前挂上主题 class，避免 :root 默认与用户选择不一致导致闪色。
            // 逻辑需与 components/chat/themes.ts 的 normalizeThemeId/applyThemeClass 保持一致。
            __html: `(function(){try{var t=localStorage.getItem('ethan-theme');if(t==='light')t='warm';var ids=['qingwa','warm','paper','mist','dark'];if(ids.indexOf(t)<0)t='qingwa';var cls=t==='dark'?'dark':'theme-'+t;var e=document.documentElement;e.classList.add(cls);if(t==='dark')e.classList.add('dark');}catch(_){}})()`,
          }}
        />
      </head>
      <body className="h-full font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
