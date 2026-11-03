import type { Metadata, Viewport } from "next";
import { DM_Sans, DM_Serif_Display } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

// TM11-142: DM Sans for UI and body text, DM Serif Display for headings.
const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const dmSerifDisplay = DM_Serif_Display({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GameGPT — describe a vibe, get games",
  description: "Natural-language game discovery across your platforms.",
};

// REQ039: must run in a mobile browser with no install.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#050a18",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${dmSans.variable} ${dmSerifDisplay.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
