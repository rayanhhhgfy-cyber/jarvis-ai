import { type ToolHandler } from "./types";

export const contentPipeline: ToolHandler = async (args, ctx) => {
  const title = args.title as string;
  const type = args.type as string || "blog";
  const platform = args.platform as string || "";
  const content = args.content as string || "";

  if (!title || !content) {
    return { success: false, error: "title and content are required" };
  }

  const validTypes = ["blog", "video", "social", "email"];
  const contentType = validTypes.includes(type) ? type : "blog";

  const entry = ctx.vault.createContent(title, contentType as "blog" | "video" | "social" | "email", content, platform);
  return { success: true, data: entry };
};
