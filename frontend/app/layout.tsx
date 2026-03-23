import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { LeagueProvider } from "@/components/layout/LeagueProvider";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Fantasy IQ — NBA Fantasy Intelligence",
  description: "AI-powered NBA Fantasy Basketball optimization platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={inter.className}>
        <LeagueProvider>{children}</LeagueProvider>
      </body>
    </html>
  );
}
