import "./styles.css";

export const metadata = {
  title: "Tally Sales Automation",
  description: "Multi-company Tally sales import workflow"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
