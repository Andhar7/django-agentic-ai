import ollama


class LLMService:

    def __init__(self, model, host=None):
        self.model = model
        self.client = ollama.Client(host=host) if host else ollama.Client()

    def generate(self, prompt):
        response = self.client.chat(
            model=self.model, messages=[{"role": "user", "content": prompt}]
        )

        return response["message"]["content"]
