// Run by explore.sh through run.sh, which supplies the test env and VERIFY_RUN.
import { saveSignIn } from "./browser"

await saveSignIn(`${process.env.VERIFY_RUN}/agent-browser-state.json`)
