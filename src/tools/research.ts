import { type ToolHandler } from "./types";

export const deepResearch: ToolHandler = async (args, ctx) => {
  const query = args.query as string;
  const depth = (args.depth as number) || 3;
  const sources = (args.sources as string) || "web";

  if (!query) {
    return { success: false, error: "query is required for deep research" };
  }

  ctx.vault.addAuditLog(ctx.agentId, "research:deep", "info", query, JSON.stringify({ depth, sources }));

  // Multi-source research synthesis
  const researchResults: string[] = [];

  // Try web fetch for research
  const searchEngines = [
    `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`,
    `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json`,
  ];

  for (const url of searchEngines) {
    try {
      const res = await fetch(url, {
        headers: {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
          "Accept": "text/html,application/json",
        },
        signal: AbortSignal.timeout(10000),
      });
      const text = await res.text();
      researchResults.push(`[Source: ${url}]\n${text.slice(0, 3000)}`);
    } catch {
      continue;
    }
  }

  // Use LLM to synthesize if available
  let synthesis = "";
  try {
    const llmResponse = await ctx.llmManager.generate([
      { role: "system", content: "You are a research analyst. Synthesize the following research data into a comprehensive, well-structured report. Include key findings, data points, and insights." },
      { role: "user", content: `Research Query: ${query}\n\nResearch Data:\n${researchResults.join("\n\n---\n\n")}\n\nProvide a thorough research report with: summary, key findings, analysis, and sources consulted.` },
    ]);
    synthesis = llmResponse.content || "";
  } catch {
    synthesis = "Research data collected but LLM synthesis unavailable. Raw data attached.";
  }

  // Record in memory for future reference
  ctx.vault.setMemory(`research:${query.slice(0, 100)}`, synthesis, "semantic", 0.8, JSON.stringify(["research", query.slice(0, 30)]));

  return {
    success: true,
    data: {
      query,
      depth,
      sources: sources.split(","),
      sourcesConsulted: researchResults.length,
      synthesis,
      rawData: researchResults.map(r => r.slice(0, 1000)),
      timestamp: new Date().toISOString(),
    },
  };
};

export const backgroundCheck: ToolHandler = async (args, ctx) => {
  const target = args.target as string;
  const context = (args.context as string) || "";
  const checkType = (args.type as string) || "general";

  if (!target) {
    return { success: false, error: "target is required for background check" };
  }

  ctx.vault.addAuditLog(ctx.agentId, "research:background_check", "info", target, JSON.stringify({ checkType, context }));

  const checks: Record<string, string> = {};

  // Web presence check
  try {
    const searchUrl = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(`${target} ${context}`)}`;
    const res = await fetch(searchUrl, {
      headers: { "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(8000),
    });
    const html = await res.text();
    const snippets = html.match(/class="result__snippet">([^<]+)</g) || [];
    checks.webPresence = snippets.slice(0, 5).map(s => s.replace(/class="result__snippet">/, "").replace(/<\/a>/g, "")).join("\n");
  } catch {
    checks.webPresence = "Web search unavailable";
  }

  // Analysis via LLM
  let analysis = "";
  try {
    const llmResponse = await ctx.llmManager.generate([
      {
        role: "system",
        content: `You are a professional background check analyst. Analyze the following information about "${target}" and provide a professional assessment. Be factual and cite any concerns neutrally.`,
      },
      {
        role: "user",
        content: `Background Check Target: ${target}\nContext: ${context}\nCheck Type: ${checkType}\n\nWeb Findings:\n${checks.webPresence}\n\nProvide a professional background assessment covering: verification status, public presence, any red flags, and overall assessment. If limited data is available, state that clearly.`,
      },
    ]);
    analysis = llmResponse.content || "";
  } catch {
    analysis = "Analysis unavailable - raw findings attached";
  }

  return {
    success: true,
    data: {
      target,
      checkType,
      timestamp: new Date().toISOString(),
      findings: checks,
      analysis,
      classification: analysis.includes("red flag") || analysis.includes("concern") ? "needs_review" : "clear",
    },
  };
};

export const webFetch: ToolHandler = async (args) => {
  const url = args.url as string;
  const format = (args.format as string) || "markdown";

  if (!url) {
    return { success: false, error: "url is required" };
  }

  try {
    const response = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      },
      signal: AbortSignal.timeout(15000),
    });

    const contentType = response.headers.get("content-type") || "";
    let content: string;

    if (contentType.includes("application/json")) {
      const json = await response.json();
      content = JSON.stringify(json, null, 2);
    } else {
      content = await response.text();
      if (format === "markdown") {
        // Basic HTML to text conversion
        content = content
          .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
          .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
          .replace(/<nav[^>]*>[\s\S]*?<\/nav>/gi, "")
          .replace(/<header[^>]*>[\s\S]*?<\/header>/gi, "")
          .replace(/<footer[^>]*>[\s\S]*?<\/footer>/gi, "")
          .replace(/<[^>]+>/g, "")
          .replace(/\s+/g, " ")
          .trim();
      }
    }

    return {
      success: true,
      data: {
        url,
        status: response.status,
        contentType,
        content: content.slice(0, 50000),
        truncated: content.length > 50000,
      },
    };
  } catch (err) {
    return { success: false, error: (err as Error).message };
  }
};

export const analyzeData: ToolHandler = async (args, ctx) => {
  const data = args.data as string;
  const analysisType = (args.type as string) || "summary";
  const context = (args.context as string) || "";

  if (!data) {
    return { success: false, error: "data is required for analysis" };
  }

  try {
    const llmResponse = await ctx.llmManager.generate([
      {
        role: "system",
        content: `You are a data analysis AI. Analyze the provided data and produce a ${analysisType}. Be thorough, identify patterns, anomalies, and key insights.`,
      },
      {
        role: "user",
        content: `Analysis Type: ${analysisType}\nContext: ${context}\n\nData:\n${data.slice(0, 15000)}\n\nProvide detailed analysis.`,
      },
    ]);

    ctx.vault.addAuditLog(ctx.agentId, "research:analyze", "info", analysisType, JSON.stringify({ context }));

    return {
      success: true,
      data: {
        type: analysisType,
        analysis: llmResponse.content,
        dataSize: data.length,
      },
    };
  } catch (err) {
    return { success: false, error: (err as Error).message };
  }
};
