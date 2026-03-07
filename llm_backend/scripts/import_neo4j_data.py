import os
import csv
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_neo4j import Neo4jGraph

# 添加项目根目录到路径
ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

# 加载环境变量
load_dotenv(ROOT_DIR / ".env")

# 修正导入路径
try:
    from app.core.config import settings
except ImportError:
    # 临时处理路径问题
    sys.path.append(str(ROOT_DIR))
    from app.core.config import settings

def import_data():
    print("Connecting to Neo4j...")
    graph = Neo4jGraph(
        url=settings.NEO4J_URL,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE
    )

    # 清空数据库
    print("Clearing database...")
    graph.query("MATCH (n) DETACH DELETE n")

    # 定义约束
    print("Creating constraints...")
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Product) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Category) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Supplier) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (cust:Customer) REQUIRE cust.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Order) REQUIRE o.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Employee) REQUIRE e.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (sh:Shipper) REQUIRE sh.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Review) REQUIRE r.id IS UNIQUE",
    ]
    for constraint in constraints:
        try:
            graph.query(constraint)
        except Exception as e:
            print(f"Constraint creation warning: {e}")

    base_path = ROOT_DIR / "app" / "graphrag" / "origin_data"
    exported_data_path = base_path / "exported_data"
    admin_data_path = base_path / "data" / "neo4j_admin"

    # 1. 导入节点
    print("Importing nodes...")
    
    # Products
    import_nodes(graph, exported_data_path / "products.csv", "Product", "ProductID", 
                 {"ProductName": "name", "QuantityPerUnit": "quantityPerUnit", "UnitPrice": "unitPrice", 
                  "UnitsInStock": "unitsInStock", "UnitsOnOrder": "unitsOnOrder", "ReorderLevel": "reorderLevel", "Discontinued": "discontinued"})

    # Categories (CategoryName as name)
    import_nodes(graph, exported_data_path / "categories.csv", "Category", "CategoryID", 
                 {"CategoryName": "name", "Description": "description"})

    # Suppliers
    import_nodes(graph, exported_data_path / "suppliers.csv", "Supplier", "SupplierID", 
                 {"CompanyName": "name", "ContactName": "contactName", "ContactTitle": "contactTitle", "City": "city", "Country": "country"})
    
    # Customers
    import_nodes(graph, exported_data_path / "customers.csv", "Customer", "CustomerID", 
                 {"CompanyName": "name", "ContactName": "contactName", "ContactTitle": "contactTitle", "City": "city", "Country": "country"})

    # Employees
    import_nodes(graph, exported_data_path / "employees.csv", "Employee", "EmployeeID", 
                 {"LastName": "lastName", "FirstName": "firstName", "Title": "title", "TitleOfCourtesy": "titleOfCourtesy", "BirthDate": "birthDate", "HireDate": "hireDate", "City": "city", "Country": "country"})

    # Orders
    import_nodes(graph, exported_data_path / "orders.csv", "Order", "OrderID", 
                 {"OrderDate": "orderDate", "RequiredDate": "requiredDate", "ShippedDate": "shippedDate", "Freight": "freight", "ShipName": "shipName", "ShipCity": "shipCity", "ShipCountry": "shipCountry"})
    
    # Shippers
    import_nodes(graph, exported_data_path / "shippers.csv", "Shipper", "ShipperID", 
                 {"CompanyName": "name", "Phone": "phone"})
                 
    # Reviews (需要确认reviews.csv字段)
    if (exported_data_path / "reviews.csv").exists():
        import_nodes(graph, exported_data_path / "reviews.csv", "Review", "reviewID", 
                     {"text": "text", "rating": "rating", "date": "date"}) 

    # 2. 导入关系 (从neo4j_admin的csv中读取)
    print("Importing relationships...")
    
    # 映射文件到关系逻辑
    # headers: :START_ID(Group),:END_ID(Group),:TYPE,...
    edge_files = [
        ("product_category_edges.csv", "Product", "Category"),
        ("product_supplier_edges.csv", "Product", "Supplier"),
        ("order_product_edges.csv", "Order", "Product"), # Has properties
        ("customer_order_edges.csv", "Customer", "Order"),
        ("employee_order_edges.csv", "Employee", "Order"),
        ("employee_reports_to_edges.csv", "Employee", "Employee"),
        ("order_shipper_edges.csv", "Order", "Shipper"),
        ("review_product_edges.csv", "Review", "Product"),
        ("customer_review_edges.csv", "Customer", "Review"),
    ]

    for filename, start_label, end_label in edge_files:
        filepath = admin_data_path / filename
        if filepath.exists():
            import_edges(graph, filepath, start_label, end_label)

    print("Import completed successfully!")

def import_nodes(graph, file_path, label, id_msg_field, property_map):
    """
    通用节点导入函数
    file_path: CSV路径
    label: Neo4j标签
    id_msg_field: CSV中的ID字段名
    property_map: CSV字段名 -> Neo4j属性名 的映射
    """
    print(f"  Loading {label} from {file_path.name}...")
    if not file_path.exists():
        print(f"    File not found: {file_path}")
        return

    data = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                props = {"id": row[id_msg_field]}
                # 类型转换处理
                if label == "Product" or label == "Order":
                     # 尝试转换数字
                     pass
                
                for csv_col, graph_prop in property_map.items():
                    if csv_col in row:
                        val = row[csv_col]
                        # 简单转换数字
                        if val.replace('.','',1).isdigit():
                             if '.' in val:
                                 val = float(val)
                             else:
                                 val = int(val)
                        props[graph_prop] = val
                
                data.append(props)
        
        # 批量写入
        batch_size = 500
        for i in range(0, len(data), batch_size):
            batch = data[i:i+batch_size]
            query = f"""
            UNWIND $batch AS row
            MERGE (n:{label} {{id: row.id}})
            SET n += row
            """
            graph.query(query, params={"batch": batch})
            
    except Exception as e:
        print(f"Error importing {label}: {e}")

def import_edges(graph, file_path, start_label, end_label):
    """
    通用关系导入函数
    """
    print(f"  Loading edges from {file_path.name}...")
    data = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            # 解析header获取索引
            # 假设 standard neo4j admin headers: :START_ID, :END_ID, :TYPE, properties...
            # 我们需要找到哪一列是START, END, TYPE, 和其他属性
            start_idx = -1
            end_idx = -1
            type_idx = -1
            prop_indices = {} # prop_name -> idx

            for i, h in enumerate(headers):
                if ":START_ID" in h:
                    start_idx = i
                elif ":END_ID" in h:
                    end_idx = i
                elif ":TYPE" in h:
                    type_idx = i
                else:
                    prop_indices[h] = i
            
            if start_idx == -1 or end_idx == -1 or type_idx == -1:
                print(f"    Invalid headers in {file_path.name}: {headers}")
                return

            for row in reader:
                if not row: continue
                # 假设ID在CSV里是纯数字ID，对应节点的id属性
                # 注意：neo4j-admin csv ID 只是ID，没有label前缀通常
                start_id = row[start_idx]
                end_id = row[end_idx]
                rel_type = row[type_idx]
                
                rels_props = {}
                for prop_name, idx in prop_indices.items():
                    val = row[idx]
                     # 简单转换数字
                    if val.replace('.','',1).isdigit():
                            if '.' in val:
                                val = float(val)
                            else:
                                val = int(val)
                    rels_props[prop_name] = val
                
                data.append({
                    "start": start_id,
                    "end": end_id,
                    "type": rel_type,
                    "props": rels_props
                })

        # 批量写入 (按类型分组，因为Cypher不能参数化类型)
        # 但这里文件通常之后一种类型，除了可能有多种？
        # neo4j-admin 导出似乎是一个文件一种类型？不一定
        # 我们按类型分组
        rels_by_type = {}
        for item in data:
            t = item["type"]
            if t not in rels_by_type: rels_by_type[t] = []
            rels_by_type[t].append(item)
        
        for r_type, items in rels_by_type.items():
            batch_size = 500
            for i in range(0, len(items), batch_size):
                batch = items[i:i+batch_size]
                # 注意：这里假设start和end节点通过'id'属性匹配，且id在CSV中是字符串还是数字要匹配
                # 我们的import_nodes把数字转了，这里start_id/end_id全是字符串读取的，也要尝试转
                # 为了简单，全部转字符串比较安全？或者全部尝试转数字？
                # CSV DictReader read strings.
                # import_nodes DID convert to int/float.
                # So we must convert start/end ids here too.
                
                cleaned_batch = []
                for x in batch:
                    s = x["start"]
                    e = x["end"]
                    if s.isdigit(): s = int(s)
                    if e.isdigit(): e = int(e)
                    cleaned_batch.append({
                        "start": s,
                        "end": e,
                        "props": x["props"]
                    })
                
                query = f"""
                UNWIND $batch AS row
                MATCH (a:{start_label} {{id: row.start}})
                MATCH (b:{end_label} {{id: row.end}})
                MERGE (a)-[r:{r_type}]->(b)
                SET r += row.props
                """
                graph.query(query, params={"batch": cleaned_batch})

    except Exception as e:
        print(f"Error importing edges {file_path.name}: {e}")

if __name__ == "__main__":
    import_data()
