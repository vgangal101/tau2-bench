import importlib
import typing
from pathlib import Path

from pydantic import BaseModel

from tau2.registry import registry
from tau2.environment.db import DB
from tau2.environment.environment import Environment
from tau2.environment.toolkit import ToolKitBase, ToolType

from schema_types import annotation_to_str


def _unwrap_optional(annotation):
    """Strip NoneType out of an Optional[...] / Union[..., None] annotation."""
    if typing.get_origin(annotation) is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _is_model(annotation) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _dict_value_model(annotation):
    """If annotation is Dict[str, SomeModel], return SomeModel, else None."""
    annotation = _unwrap_optional(annotation)
    if typing.get_origin(annotation) in (dict,):
        args = typing.get_args(annotation)
        if len(args) == 2 and _is_model(args[1]):
            return args[1]
    return None


def _list_value_type(annotation):
    """If annotation is List[X], return X, else None."""
    annotation = _unwrap_optional(annotation)
    if typing.get_origin(annotation) in (list,):
        args = typing.get_args(annotation)
        if args:
            return args[0]
    return None


def _describe_return(annotation) -> dict:
    """Characterize a tool's return annotation.

    Unwraps ``Optional[...]`` and ``List[...]`` to recover the underlying
    return type and reports:
      * ``entity``: the type name of the returned value -- the pydantic model
        name for DB/domain entities (e.g. ``Reservation``/``User``/
        ``DirectFlight``), or the scalar type name (``str``, ``int``, ...);
      * ``cardinality``: ``"list"`` when the tool returns a collection, else
        ``"single"``;
      * ``is_db_entity``: whether the returned type is a pydantic model (a
        DB/domain entity) as opposed to a plain scalar.
    """
    inner = _unwrap_optional(annotation)
    list_inner = _list_value_type(inner)
    if list_inner is not None:
        cardinality = "list"
        inner = _unwrap_optional(list_inner)
    else:
        cardinality = "single"

    return {
        "entity": getattr(inner, "__name__", str(inner)),
        "cardinality": cardinality,
        "is_db_entity": _is_model(inner),
    }


class AugmentedPDDLlikeSchema:
    """
    Augmented Schema that provides precondition/effect structure,
    as well as auxiliary information needed to characterize TauBench tasks.

    Note that this works only for Airline, Retail
    """

    def __init__(self, env_names: list[str]):
        self.build_env_names = env_names
        # Instantiate each requested environment via the tau2 registry and keep
        # the running instances around to build schemas from.
        self.environments: dict[str, Environment] = {}
        # The domain DB pydantic model class (e.g. FlightDB, RetailDB), resolved
        # programmatically per domain rather than imported by name.
        self.db_models: dict[str, type[DB]] = {}
        # The loaded DB instance (db.json validated against the domain DB model).
        self.dbs: dict[str, DB] = {}
        # The domain toolkit instance (e.g. AirlineTools, RetailTools) -- this is
        # where the tool schemas/signatures are extracted from.
        self.toolkits: dict[str, ToolKitBase] = {}
        for env_name in self.build_env_names:
            env = self._load_environment(env_name)
            self.environments[env_name] = env
            db_model = self._load_db_model(env_name)
            self.db_models[env_name] = db_model
            self.dbs[env_name] = db_model.load(self._load_db_path(env_name))
            self.toolkits[env_name] = env.tools

    @staticmethod
    def _load_environment(env_name: str) -> Environment:
        """Programmatically import and instantiate a domain environment by name."""
        get_environment = registry.get_env_constructor(env_name)
        return get_environment()

    @staticmethod
    def _load_db_model(env_name: str) -> type[DB]:
        """Programmatically import the domain's DB model class (e.g. FlightDB).

        Imports ``tau2.domains.<env_name>.data_model`` and returns its single
        concrete ``DB`` subclass, so no per-domain import has to be hardcoded.
        """
        module = importlib.import_module(f"tau2.domains.{env_name}.data_model")
        db_models = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type) and issubclass(obj, DB) and obj is not DB
        ]
        if len(db_models) != 1:
            raise ValueError(
                f"Expected exactly one DB model in {module.__name__}, "
                f"found {[m.__name__ for m in db_models]}"
            )
        return db_models[0]

    @staticmethod
    def _load_db_path(env_name: str) -> Path:
        """Programmatically resolve the domain's db.json path (e.g. AIRLINE_DB_PATH).

        Imports ``tau2.domains.<env_name>.utils`` and returns its single
        ``*_DB_PATH`` constant.
        """
        utils = importlib.import_module(f"tau2.domains.{env_name}.utils")
        db_paths = [
            value for name, value in vars(utils).items() if name.endswith("_DB_PATH")
        ]
        if len(db_paths) != 1:
            raise ValueError(
                f"Expected exactly one *_DB_PATH in {utils.__name__}, found {db_paths}"
            )
        return Path(db_paths[0])

    def build_schemas(self) -> dict[str, dict]:
        """Build an augmented schema for every running environment."""
        return {
            name: self._build_schema(name)
            for name in self.environments
        }

    @staticmethod
    def analyze_env_db(env: Environment) -> dict:
        """
        Inspect an environment's database and recover its relational structure.

        Returns a mapping of table name -> {record_model, primary_key,
        foreign_keys}, where:
          * a "table" is a top-level ``Dict[str, RecordModel]`` field on the DB
            (e.g. retail ``users``/``orders``/``products``);
          * the primary key is the record field whose value indexes the table
            (detected against the loaded data so non-``*_id`` keys such as the
            airline ``flight_number`` are found correctly);
          * foreign keys are record fields (possibly nested) that reference
            another table's primary key, either as a scalar id or a list of ids.
        """
        db = env.tools.db
        db_model = type(db)

        # 1. Discover tables: top-level Dict[str, RecordModel] fields.
        tables: dict[str, type[BaseModel]] = {}
        for name, field in db_model.model_fields.items():
            record_model = _dict_value_model(field.annotation)
            if record_model is not None:
                tables[name] = record_model

        # 2. Resolve each table's primary key against the loaded records.
        primary_keys: dict[str, str] = {}
        for table_name, record_model in tables.items():
            records = getattr(db, table_name)
            primary_keys[table_name] = AugmentedPDDLlikeSchema._detect_primary_key(
                table_name, record_model, records
            )

        # Index: pk field name -> table, used to recognise foreign-key fields.
        pk_field_to_table = {
            pk: table_name for table_name, pk in primary_keys.items()
        }

        # 3. For each table, collect foreign keys.
        result: dict[str, dict] = {}
        for table_name, record_model in tables.items():
            pk = primary_keys[table_name]
            fks = AugmentedPDDLlikeSchema._collect_foreign_keys(
                record_model,
                own_table=table_name,
                own_pk=pk,
                pk_field_to_table=pk_field_to_table,
                primary_keys=primary_keys,
                table_names=set(tables),
            )
            result[table_name] = {
                "record_model": record_model.__name__,
                "primary_key": pk,
                "foreign_keys": fks,
            }
        return {"tables": result}

    @staticmethod
    def _detect_primary_key(table_name, record_model, records: dict) -> str:
        """Find the record field that indexes ``records`` (its primary key)."""
        fields = list(record_model.model_fields)

        # Data-driven: the PK is the scalar field whose value equals the dict key
        # for every record.
        if records:
            for fname in fields:
                if all(
                    isinstance(getattr(rec, fname, None), (str, int))
                    and str(getattr(rec, fname)) == str(key)
                    for key, rec in records.items()
                ):
                    return fname

        # Fallbacks for empty tables: <singular>_id, then a "Unique ..." field,
        # then the first id-ish field.
        singular_id = f"{table_name.rstrip('s')}_id"
        if singular_id in fields:
            return singular_id
        for fname, finfo in record_model.model_fields.items():
            desc = (finfo.description or "").lower()
            if desc.startswith("unique"):
                return fname
        for fname in fields:
            if fname.endswith("_id") or fname.endswith("_number"):
                return fname
        return fields[0] if fields else ""

    @staticmethod
    def _collect_foreign_keys(
        record_model,
        own_table,
        own_pk,
        pk_field_to_table,
        primary_keys,
        table_names,
    ) -> list[dict]:
        """Walk a record model (incl. nested models) and report foreign keys."""
        fks: list[dict] = []
        visited: set[type] = set()

        def walk(model, path):
            if model in visited:
                return
            visited.add(model)
            for fname, finfo in model.model_fields.items():
                dotted = f"{path}{fname}"
                annotation = finfo.annotation

                # Scalar id reference: field name matches another table's PK.
                if fname in pk_field_to_table:
                    ref_table = pk_field_to_table[fname]
                    is_self_pk = path == "" and fname == own_pk
                    if not is_self_pk:
                        fks.append(
                            {
                                "field": dotted,
                                "references_table": ref_table,
                                "references_key": fname,
                                "kind": "scalar",
                            }
                        )
                    continue

                # Collection of ids: List[str] field named after another table.
                list_inner = _list_value_type(annotation)
                if (
                    list_inner in (str,)
                    and fname in table_names
                    and fname != own_table
                ):
                    fks.append(
                        {
                            "field": dotted,
                            "references_table": fname,
                            "references_key": primary_keys[fname],
                            "kind": "collection",
                        }
                    )
                    continue

                # Descend into nested models and into list/dict of models.
                nested = (
                    (_is_model(_unwrap_optional(annotation)) and _unwrap_optional(annotation))
                    or _dict_value_model(annotation)
                    or (_is_model(list_inner) and list_inner)
                    or None
                )
                if nested is not None:
                    walk(nested, f"{dotted}.")

        walk(record_model, "")
        return fks

    def _build_schema(self, env_name: str) -> dict:
        """
        Build the augmented PDDL-like schema for a single environment.

        TODO: implement. Tool signatures alone are not enough -- this should
        derive precondition/effect structure plus the auxiliary information
        needed to characterize TauBench tasks.

        - Characterize the API-Dependency-Graph, need to maintain the input arguments , and the outputs of each tool-call.
        """

        # to start, for each tool call signature, make a list of all the input
        # arguments for a tool, put that in the schema. Alongside, record the
        # output: the DB/domain entity the tool returns (name + cardinality),
        # which is what the API-Dependency-Graph links producers to consumers on.
        toolkit = self.toolkits[env_name]

        tools: dict[str, dict] = {}
        for name, tool in toolkit.get_tools().items():
            # Only READ and WRITE tools belong in the schema; THINK/GENERIC
            # utilities (e.g. think, calculate) don't touch DB/domain entities
            # and aren't part of the API-Dependency-Graph.
            tool_type = toolkit.tool_type(name)
            if tool_type not in (ToolType.READ, ToolType.WRITE):
                continue
            # tool.params / tool.returns are pydantic models built from the
            # function signature; the actual return annotation lives on the
            # synthetic "returns" field of tool.returns.
            return_annotation = tool.returns.model_fields["returns"].annotation
            tools[name] = {
                "type": tool_type.value,
                # input arg name -> normalized type string, so the dependency
                # graph can match consumer inputs to producer output fields on
                # both name and type.
                "inputs": {
                    pname: annotation_to_str(pfield.annotation)
                    for pname, pfield in tool.params.model_fields.items()
                },
                "output": _describe_return(return_annotation),
            }

        return {"tools": tools}


def main():
    import json

    artifacts_dir = Path("analysis_code/artifacts")
    db_metadata_dir = artifacts_dir / "db_metadata"
    db_metadata_dir.mkdir(parents=True, exist_ok=True)
    schema_dir = artifacts_dir / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)

    builder = AugmentedPDDLlikeSchema(env_names=["retail", "airline"])
    schemas = builder.build_schemas()
    for env_name, env in builder.environments.items():
        db_analysis = builder.analyze_env_db(env)
        out_file = db_metadata_dir / f"{env_name}_db_metadata.json"
        with open(out_file, "w") as f:
            json.dump(db_analysis, f, indent=2)
        print(f"Wrote {env_name} DB metadata to {out_file}")

        schema_file = schema_dir / f"{env_name}_augmented_schema.json"
        with open(schema_file, "w") as f:
            json.dump(schemas[env_name], f, indent=2)
        print(f"Wrote {env_name} augmented schema to {schema_file}")


if __name__ == "__main__":
    main()
