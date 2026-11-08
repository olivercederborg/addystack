import { capsule, endpoint, text } from "lakebed/server";
import { LLMS, LLMS_TXT, NAME } from "../shared/llms";

const markdownHeaders = {
  "Content-Type": "text/markdown; charset=utf-8",
  Link: '</>; rel="alternate"; type="text/html"',
  "X-Content-Type-Options": "nosniff",
};

export default capsule({
  name: NAME,
  endpoints: {
    llmsMarkdown: endpoint({ method: "GET", path: "/llms.md" }, () => text(LLMS, { headers: markdownHeaders })),
    indexMarkdown: endpoint({ method: "GET", path: "/index.md" }, () => text(LLMS, { headers: markdownHeaders })),
    llmsText: endpoint({ method: "GET", path: "/llms.txt" }, () =>
      text(LLMS_TXT, { headers: { "Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff" } }),
    ),
  },
});
