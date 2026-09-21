import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Incident Room",
  description: "Deterministic cyber-incident training console",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        {children}
        {process.env.NEXT_PUBLIC_GIT_COMMIT && (
          <span className="build-info" title="Build commit">
            {process.env.NEXT_PUBLIC_GIT_COMMIT}
          </span>
        )}
      </body>
    </html>
  );
}
