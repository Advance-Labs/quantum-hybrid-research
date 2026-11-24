import { NextResponse, type NextFetchEvent, type NextRequest } from 'next/server';

// AI bot-hit collector (aeo-platform docs/AI-BOT-COLLECTOR.md). Fire-and-forget; no-ops without AEO_COLLECTOR_KEY.
// Training crawlers (GPTBot, ClaudeBot, Meta-ExternalAgent, Bytespider, CCBot) are deliberately not forwarded (2026-11-24, Redis/collector volume); the list mirrors the user+search kinds in aeo-platform classify.ts.
const AI_BOTS =
  /(?:^|[^A-Za-z0-9-])(ChatGPT-User|OAI-SearchBot|Claude-User|Claude-SearchBot|Perplexity-User|PerplexityBot|MistralAI-User|DuckAssistBot|Meta-ExternalFetcher|Amazonbot)(?![A-Za-z0-9-])/i;

export function proxy(request: NextRequest, event: NextFetchEvent) {
  const ua = (request.headers.get('user-agent') ?? '').slice(0, 512);
  const key = process.env.AEO_COLLECTOR_KEY;
  if (key && AI_BOTS.test(ua)) {
    event.waitUntil(
      fetch('https://aeo.advancelabs.dev/api/collect/ai-bots', {
        method: 'POST',
        headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json' },
        body: JSON.stringify({
          events: [
            {
              ua,
              path: request.nextUrl.pathname,
              ts: Date.now(),
              ip:
                request.headers.get('x-real-ip') ??
                request.headers.get('x-forwarded-for')?.split(',')[0]?.trim(),
            },
          ],
        }),
      }).catch(() => {}),
    );
  }
  return NextResponse.next();
}

export const config = { matcher: ['/((?!_next/|favicon.ico).*)'] };
