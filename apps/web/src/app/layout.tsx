import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import cx from "@/utils/cx";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Rivet AI",
  description:
    "Rivet AI is a general-purpose AI assistant for questions, explanations, writing and summaries.",
  applicationName: "Rivet AI",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="scroll-smooth antialiased">
      <head>
        {/* runs before client code: the API URL comes from the server's env */}
        <Script
          id="rivet-runtime-config"
          src="/config.js"
          strategy="beforeInteractive"
        />
      </head>
      <body
        className={cx(
          inter.className,
          "text-sm md:text-base bg-neutral-950 text-neutral-100",
        )}
      >
        {children}
      </body>
    </html>
  );
}
