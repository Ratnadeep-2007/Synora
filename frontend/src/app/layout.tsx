import type { Metadata } from "next";
import "./globals.css";
import "./excalidraw.css";

export const metadata: Metadata = {
  title: "Synesis — Project Intelligence & AI Workforce Platform",
  description: "Maintain a reliable, continuously updated representation of what your team is building.",
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
