# Example Structural Analysis Tasks

These examples demonstrate how to use the updated `config/default_with_mcp.yaml` for sophisticated software engineering tasks that leverage CAST Imaging structural analysis.

## Task 1: Microservice Extraction from Monolith

**Task Description:**
"Extract the order processing functionality from the shopizer_back_end monolithic e-commerce application into a separate microservice. Ensure minimal coupling and identify all affected APIs and data flows."

**Expected Workflow:**
1. Use `applications` to identify shopizer_back_end
2. Use `stats` to understand the overall architecture (272 APIs, 53 data flows)
3. Use `find_code_structures` with query "order" to find order-related code
4. Use `transaction_details` on order-related APIs to understand call graphs
5. Use `graph_intersection_analysis` to identify shared code that could cause coupling
6. Use `object_details` with inward/outward focus to map dependencies
7. Use `data_graph_details` to understand data dependencies
8. Create extraction plan minimizing architectural coupling

## Task 2: Critical CVE Remediation with Impact Analysis

**Task Description:**
"Remediate the CRITICAL CVE-2019-17495 (CSS injection in Swagger UI) in shopizer_back_end while ensuring no regression in the 272 public APIs or 53 data flows."

**Expected Workflow:**
1. Use `quality_insights` with nature=cve to list all CVEs
2. Use `quality_insight_occurrences` to find exact code locations of CVE-2019-17495
3. Use `object_details` on affected objects to understand dependencies
4. Use `transactions` to identify APIs that could be affected
5. Plan remediation with minimal architectural impact
6. Implement fix and validate no regression in structural metrics

## Task 3: API Modernization with Architecture Evolution

**Task Description:**
"Modernize the REST API layer in shopizer_back_end from Spring MVC to Spring WebFlux for reactive programming, ensuring backward compatibility and optimal transaction performance."

**Expected Workflow:**
1. Use `architectural_graph` to understand current layers (User Interaction, Logic Services, etc.)
2. Use `transactions` to inventory all 272 APIs and their technology stacks
3. Use `transaction_details` to analyze complexity and call patterns
4. Use `advisors` to identify modernization recommendations
5. Use `graph_intersection_analysis` to find shared components
6. Plan migration strategy respecting architectural boundaries
7. Implement changes with structural validation

## Task 4: Database Performance Optimization

**Task Description:**
"Optimize database access patterns in shopizer_back_end data layer (57 Database Services objects) by identifying inefficient queries and implementing caching strategies."

**Expected Workflow:**
1. Use `architectural_graph` to focus on Database Services component
2. Use `data_graphs` to analyze all 53 data flows
3. Use `data_graph_details` with complexity focus to find inefficient patterns
4. Use `database_explorer` to understand table relationships
5. Use `object_details` on database objects to map usage patterns
6. Implement optimizations guided by structural analysis

## Running These Tasks

To run these examples with the updated config:

```bash
# Example command structure (adjust paths and parameters as needed)
python -m sweagent.run.run_single \
  --config_file config/default_with_mcp.yaml \
  --model_name "anthropic/claude-3-5-sonnet-20241022" \
  --repo_path /path/to/target/repository \
  --problem_statement "$(cat examples/task_description.txt)"
```

## Key Benefits of Structural Analysis Approach

1. **Architecture Awareness**: Understanding layers, components, and coupling before making changes
2. **Impact Analysis**: Knowing exactly what transactions, data flows, and objects will be affected
3. **Quality Focus**: Identifying and remediating CVEs, structural flaws, and ISO 5055 violations
4. **Modernization Guidance**: Using advisor recommendations for strategic improvements
5. **Dependency Intelligence**: Making changes that respect architectural boundaries
6. **Testing Strategy**: Comprehensive test planning based on structural dependencies