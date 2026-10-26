"""Exercise the installed generate wrapper without loading weights or a GPU."""
import unittest
from types import SimpleNamespace
import torch
from transformers import GenerationConfig
from llm.qa_factory.model import LocalModel


class Inputs(dict):
    def __init__(self):
        super().__init__(input_ids=torch.tensor([[1, 2, 3]]))
        self.input_ids = self['input_ids']
    def to(self, device):
        return self


class Tokenizer:
    eos_token_id = 9
    def apply_chat_template(self, *args, **kwargs):
        return 'test prompt'
    def __call__(self, *args, **kwargs):
        return Inputs()
    def decode(self, *args, **kwargs):
        return 'test output'


class Model:
    device = 'cpu'
    config = SimpleNamespace(max_position_embeddings=64)
    generation_config = GenerationConfig(eos_token_id=[9, 10], do_sample=True,
                                         temperature=0.7, top_p=0.8, top_k=20)
    def forward(self, input_ids, logits_to_keep=0):
        pass
    def generate(self, **kwargs):
        self.kwargs = kwargs
        return torch.tensor([[1, 2, 3, *self.output]])


class GenerationMetadataTests(unittest.TestCase):
    def backend(self, tokens):
        backend = LocalModel.__new__(LocalModel)
        backend.torch, backend.model_id = torch, 'test-backend'
        backend.model, backend.tokenizer = Model(), Tokenizer()
        backend.model.output = tokens
        return backend

    def test_eos_at_budget_is_not_truncation_and_sampling_is_disabled(self):
        backend = self.backend([5, 9])
        result = backend.generate([], 2)
        self.assertEqual(result['finish_reason'], 'eos')
        self.assertFalse(result['token_limit_reached'])
        self.assertEqual(result['output_tokens'], 2)
        self.assertFalse(backend.model.kwargs['generation_config'].do_sample)
        self.assertEqual(backend.model.kwargs['logits_to_keep'], 1)
        self.assertEqual(backend.model.generation_config.temperature, 0.7)

    def test_length_stop_and_context_overflow_are_explicit(self):
        backend = self.backend([5, 6])
        self.assertEqual(backend.generate([], 2)['finish_reason'], 'length')
        with self.assertRaisesRegex(ValueError, 'not truncated'):
            backend.generate([], 64)
        with self.assertRaises(ValueError):
            backend.generate([], 0)


if __name__ == '__main__':
    unittest.main()
