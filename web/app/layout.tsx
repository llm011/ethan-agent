import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ethan Agent",
  description: "Personal AI Agent",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased dark" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){var t=localStorage.getItem('ethan-theme');if(t==='light'){document.documentElement.classList.remove('dark');document.documentElement.classList.add('light');}})()`,
          }}
        />
      </head>
      <body className="h-full font-sans">{children}</body>
    </html>
  );
}
