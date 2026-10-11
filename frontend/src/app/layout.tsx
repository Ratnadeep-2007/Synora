import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import "./cinematic.css";
import "./excalidraw.css";
const geist = localFont({ src: "./fonts/GeistVF.woff", variable: "--font-geist", display: "swap" });

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
      <body className={`${geist.variable} antialiased bg-canvas text-text-main`}>
        {/* Runtime backend URL (SYNORA_API_URL). Plain script so it executes
            before page bundles; api.ts reads window.__SYNORA_API_URL__. */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/runtime-config.js" />
        {children}
      </body>
    </html>
  );
}
