import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ERP Analyst Agent",
  description: "Ask analytics questions over a synthetic multi-tenant manufacturing ERP.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
