import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Guitar Tone Advisor",
  description: "Grounded guitar tone recommendations from cited sources",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className="bg-zinc-950 text-zinc-50 h-full">{children}</body>
    </html>
  );
}
