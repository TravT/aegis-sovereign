import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Aegis Sovereign Vault — Executive Intelligence Portal',
  description:
    'Air-gapped document intelligence and high-precision knowledge retrieval appliance for sovereign enterprises.',
  icons: {
    icon: '/favicon.ico',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR" className="dark bg-[#07090D] text-[#E6EDF3]">
      <head>
        <meta name="theme-color" content="#07090D" />
      </head>
      <body className="min-h-screen bg-[#07090D] antialiased selection:bg-[#D4AF37]/30 selection:text-[#F3E5AB]">
        {children}
      </body>
    </html>
  );
}
