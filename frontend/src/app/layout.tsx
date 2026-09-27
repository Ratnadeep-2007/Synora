import type { Metadata } from "next";
import "./globals.css";
import "./excalidraw.css";

export const metadata: Metadata = {
  title: "Synora — Project Intelligence & Living Architecture",
  description: "One shared Synora Agent maintaining an evidence-backed, versioned project state and living visual workspace.",
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
