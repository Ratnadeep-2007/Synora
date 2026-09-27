import type { Metadata } from "next";
import "./globals.css";
import "./excalidraw.css";

export const metadata: Metadata = {
  title: "Synora — Autonomous Project Intelligence & Living Architecture",
  description: "One shared intelligence layer maintaining an authoritative, continuously updated visual architecture.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased bg-canvas text-text-main">
        {children}
      </body>
    </html>
  );
}
