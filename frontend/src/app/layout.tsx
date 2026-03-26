import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "PaperTrade - Learn to Invest Risk-Free",
  description:
    "Practice investing with virtual money. Trade stocks and crypto without risk.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <Providers>
          {children}
          <footer className="w-full border-t border-zinc-800 mt-12 py-6 px-4 text-center text-xs text-zinc-500">
            <p>
              PaperTrade is an educational tool for learning about investing with virtual money.
              Nothing on this site constitutes financial advice. All trades are simulated; no real money is involved.
            </p>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
