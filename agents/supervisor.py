VALID_ROUTES = {"greeting", "search", "summary", "parallel"}
GREETING_KEYWORDS = {"hello", "hi", "hey", "namaste", "good morning", "good evening"}
SUMMARY_KEYWORDS = {"summarize", "summarise", "summary"}
SEARCH_KEYWORDS = {"find", "search", "look up", "lookup"}


class SupervisorAgent:

    def __init__(self, llm_service):
        self.llm_service = llm_service

    def decide_route(self, message):
        try:
            return self._classify_with_llm(message)
        except Exception:
            return self._classify_with_keywords(message)

    def _classify_with_llm(self, message):
        prompt = (
            "Classify the user's message into exactly one category: "
            "greeting, search, summary, or parallel. "
            "Respond with exactly one word, nothing else.\n\n"
            f"Message: {message}"
        )
        raw = self.llm_service.generate(prompt)
        route = raw.strip().lower()

        if route not in VALID_ROUTES:
            raise ValueError(f"Unexpected route from LLM: {raw!r}")

        return route

    def _classify_with_keywords(self, message):

        lowered = message.lower()

        if any(word in lowered for word in GREETING_KEYWORDS):
            return "greeting"
        if any(word in lowered for word in SUMMARY_KEYWORDS):
            return "summary"
        if any(word in lowered for word in SEARCH_KEYWORDS):
            return "search"

        return "parallel"
