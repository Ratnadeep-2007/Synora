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
        {/* Runtime backend URL (SYNORA_API_URL). Plain script so it executes
            before page bundles; api.ts reads window.__SYNORA_API_URL__. */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/runtime-config.js" />
        {children}
      </body>
    </html>
  );
}
