import "./styles.css";

export const metadata = {
  title: "AccountPilot",
  description: "Multi-company Tally sales import workflow"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
