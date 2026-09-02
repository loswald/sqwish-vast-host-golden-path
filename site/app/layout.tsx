import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000',
  ),
  title: 'Sqwish GPU Slack Lab',
  description:
    'Explore the economics and tested operating limits of renting spare Sqwish GPUs on Vast.ai, draining them for research, and relisting them afterward.',
  openGraph: {
    title: 'Sqwish GPU Slack Lab',
    description:
      'Model spare-GPU rentals, research demand, and the tested limits of Vast.ai interruptible capacity.',
    images: [{ url: '/og.png', width: 1536, height: 1024 }],
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Sqwish GPU Slack Lab',
    description:
      'Explore spare-GPU economics and the tested limits of reclaiming Vast.ai interruptible capacity for research.',
    images: ['/og.png'],
  },
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
        {children}
      </body>
    </html>
  );
}
