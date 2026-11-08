import { useEffect } from "preact/hooks";
import { BODY, CSS, TITLE } from "../shared/page";

/** Renders the review artifact: its stylesheet, its body markup, and a link to /llms.md. */
export function App() {
  useEffect(() => {
    document.title = TITLE;
    const style = document.createElement("style");
    style.textContent = CSS;
    const scheme = document.createElement("meta");
    scheme.name = "color-scheme";
    scheme.content = "light dark";
    const alternate = document.createElement("link");
    alternate.href = "/llms.md";
    alternate.rel = "alternate";
    alternate.type = "text/markdown";
    document.head.append(style, scheme, alternate);
    return () => {
      style.remove();
      scheme.remove();
      alternate.remove();
    };
  }, []);

  return <main dangerouslySetInnerHTML={{ __html: BODY }} />;
}
