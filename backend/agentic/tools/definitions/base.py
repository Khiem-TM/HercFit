"""Backend tool contract and declaration; execution always uses ToolAgent."""
from dataclasses import dataclass
from typing import Any
from pydantic import BaseModel
from langchain_core.tools import StructuredTool

@dataclass(frozen=True)
class ToolSpec:
    name: str
    domain: str
    method: str
    path: str
    schema: type[BaseModel]
    output: Any
    description: str
    body: bool = False

    @property
    def write(self):
        return self.method != 'GET'

    def normalize(self, args):
        value = self.schema.model_validate(args)
        # Materialize defaults only for creates, so previews contain the exact
        # timestamps/defaults that will be sent. PATCH/PUT preserve omissions.
        return value.model_dump(mode='json', exclude_unset=self.method != 'POST')

    def request_parts(self, args):
        args = dict(args)
        resource_id = args.pop('resource_id', None)
        path = self.path.format(resource_id=resource_id)
        return path, ({} if self.body else args), (args if self.body else None)

    def as_tool(self):
        async def declaration(**kwargs):
            raise RuntimeError('Tools must execute through the approval-aware adapter')
        return StructuredTool.from_function(coroutine=declaration, name=self.name,
                                            description=self.description, args_schema=self.schema)
