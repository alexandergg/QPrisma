# QPrisma Frontend

Frontend application for QPrisma - Intelligent Multimedia Processing Platform.

Built with [Next.js 16](https://nextjs.org), React 19, and TypeScript.

## Quick Start

```bash
# Install dependencies
npm install

# Set up environment
cp .env.local.example .env.local

# Run development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to view the application.

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server |
| `npm run build` | Build for production |
| `npm run start` | Start production server |
| `npm run lint` | Run ESLint |
| `npm run lint:fix` | Fix ESLint issues |
| `npm run typecheck` | Run TypeScript type checking |

## Project Structure

```
frontend/
├── app/                    # Next.js App Router pages
│   ├── auth/               # Authentication pages
│   ├── chat/               # Chat interface
│   ├── library/            # Media library
│   ├── upload/             # Upload page
│   └── video/[id]/         # Video detail page
├── components/             # React components
│   ├── chat/               # Chat components
│   ├── layout/             # Layout components
│   ├── library/            # Library components
│   └── upload/             # Upload components
├── contexts/               # React contexts
├── hooks/                  # Custom React hooks
├── lib/                    # Utilities and API client
└── public/                 # Static assets
```

## Environment Variables

Create a `.env.local` file (see `.env.local.example`):

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Backend API URL (default: http://localhost:8000) |

## Tech Stack

- **Framework**: Next.js 16 with App Router
- **UI**: React 19 + Tailwind CSS
- **Icons**: Lucide React
- **Data Fetching**: SWR
- **Flow Diagrams**: ReactFlow
- **Language**: TypeScript
