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
    <html lang="en" className="h-full antialiased dark">
      <body className="h-full font-sans">{children}</body>
    </html>
  );
}
