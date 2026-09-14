import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Incident Room",
  description: "Deterministic cyber-incident training console",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
