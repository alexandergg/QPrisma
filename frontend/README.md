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
│   ├── chat/               # Chat interface and video selection state
│   ├── library/            # Media library
│   ├── upload/             # Upload page
│   └── compare/            # Multi-video comparison
├── components/             # React components
│   ├── chat/               # Chat components
│   ├── graph/              # Knowledge graph visualization
│   ├── layout/             # Layout components
│   ├── library/            # Library components
│   ├── ui/                 # Shared UI primitives
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

## Frontend Architecture Notes

### Chat and video transitions

- Video cards route to `/chat?videoId=<media-id>` through `lib/routes.ts`.
- `app/chat/useChatVideos.ts` reads the URL `videoId`, loads media metadata and structure, and exposes a pending state while the video opens.
- `components/chat/ChatContainer.tsx` renders an explicit “Opening video” state during that pending load so the default welcome screen does not flash between a library/dashboard click and the video chat view.
- `app/chat/[id]/page.tsx` is a compatibility redirect for removed local conversation persistence.

### Upload and Databricks processing status

- `/upload` and the chat upload modal share `components/upload/UploadZone`, `ProcessingCard`, `ProcessingStep`, and `useJobProgress`.
- Small uploads use `apiClient.uploadVideoOptimized`; large uploads use `lib/chunked-upload.ts`.
- Processing status is read from `apiClient.getMediaStatus(mediaId)`, which polls `GET /media/{media_id}/status`.
- The current backend status path is Service Bus dispatch → Function bridge → Databricks Delta outbox → PostgreSQL projection → media status API.
- Event Hubs are not wired in the current frontend/backend path. If near-real-time status is needed later, add a backend-owned streaming contract rather than connecting the browser to Databricks or raw cloud events.
- `processing_progress` is normalized in the API client so both fractional Databricks progress (`0.0`-`1.0`) and percent-style values (`0`-`100`) render consistently.

### Cleanup conventions

- Keep route-mounted code under `app/` and active shared components under their domain folders (`chat`, `library`, `upload`, `graph`, `layout`, `ui`).
- Avoid reintroducing broad barrel exports for components that are not mounted by active routes.
- Use `lib/dynamic.tsx` only for heavy active-route components; currently this is the knowledge graph viewer.

## Tech Stack

- **Framework**: Next.js 16 with App Router
- **UI**: React 19 + Tailwind CSS
- **Icons**: Lucide React
- **Data Fetching**: SWR
- **Motion**: Framer Motion
- **Language**: TypeScript
