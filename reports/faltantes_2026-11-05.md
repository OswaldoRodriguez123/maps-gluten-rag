# Restaurantes con poca data — después de P0, visión y tiendas

_Fecha: 2026-11-05 · Fuente: Doc regenerado con normalización P0 + visión + catálogos web_

## Resumen

- **100 lugares** en la lista.
- **76 con platos publicables**: 3429 platos.
- **1 solo con categorías** (sin platos específicos).
- **23 sin carta ni categorías**: 15 sin web y 8 con web.
- **19 con carta corta** (1-9 platos).
- **17 con menos del 50% de precios**.
- **4 con mucho ruido** (revisión + rechazados >= 20).
- **33 sin web registrada**.
- **4 sin ningún dato** (sin web, sin menciones, sin reseñas, sin carta).

## 1. Sin carta ni categorías y sin web (solo reseñas o nada)

| name | cat | web_n | rev_n | review | rejected |
|---|---|---|---|---|---|
| SERSAYAAN ALIMENTOS SIN GLUTEN | Cafetería | 0 | 7 | 0 | 0 |
| Simona Healthy Bakery | Pastelería | 0 | 6 | 0 | 0 |
| Cafetería Molino | Cafetería apta para perros | 0 | 4 | 0 | 0 |
| Lighthouse Bakery | Cafetería | 0 | 4 | 0 | 0 |
| Cafetería y Pastelería Fabiana | Cafetería | 0 | 3 | 0 | 0 |
| Helados Quinto Pino | Heladería | 0 | 3 | 0 | 0 |
| Kanu Cocina | Comida hindú para llevar | 0 | 2 | 0 | 0 |
| guffsushi.cl | Restaurante de sushi | 0 | 2 | 0 | 0 |
| CASI PERFECTO | Tienda naturista | 0 | 1 | 0 | 0 |
| REFUGIO PUB ÑUÑOA | Pub | 0 | 1 | 0 | 0 |
| VICTORIA KETO | Cafetería | 0 | 1 | 0 | 0 |
| Glutón | Sin categoría | 0 | 0 | 0 | 0 |
| Mercado Condell | Centro comercial | 0 | 0 | 0 | 0 |
| Montenegro 391 | Sin categoría | 0 | 0 | 0 | 0 |
| Mr Foodie | Supermercado | 0 | 0 | 1 | 0 |

## 2. Sin carta ni categorías, pero con web (revisar web/JSON-LD)

| name | cat | web_n | rev_n | review | rejected | url |
|---|---|---|---|---|---|---|
| Sabores para Alegrar | Pastelería | 11 | 4 | 0 | 0 | http://www.saboresparaalegrar.cl/ |
| Massanoglutenfree | Pastelería | 7 | 2 | 0 | 0 | http://www.massanoglutenfree.cl/ |
| Libre Punto SpA | Tienda de alimentos naturales | 4 | 0 | 0 | 0 | http://www.librepunto.cl/ |
| Popolo Pizza sin Gluten | Pizzería a domicilio | 2 | 1 | 0 | 0 | http://www.popolo.cl/ |
| CO&keto | Cafetería | 0 | 4 | 0 | 0 | http://www.cokefoods.cl/ |
| Casa Roque Chocolates | Centro comercial | 0 | 1 | 0 | 0 | https://wwww.casaroque.cl/ |
| Glutenberg | Pastelería | 0 | 4 | 0 | 0 | https://www.glutenberg.cl/ |
| Jardin de Gente | Cafetería | 0 | 3 | 0 | 0 | http://www.jardindegente.cl/ |

## 3. Solo categorías (saben qué venden, pero no hay platos)

- **La Comarca Celiaca**: Sandwiches, Empanadas, Sopaipillas, Pizzas, Pasteleria, Jugos Naturales

## 4. Carta corta (1-9 platos)

| name | cat | dishes | prices | review | rejected |
|---|---|---|---|---|---|
| BAR EL BAJO | Bar | 1 | 1 | 2 | 2 |
| Emporio de la Tierra | Tienda de alimentos naturales | 1 | 0 | 0 | 0 |
| Fain | Tienda de alimentos naturales | 1 | 1 | 0 | 0 |
| Las Petunias Pastelería sin azúcar y sin gluten | Pastelería | 1 | 0 | 1 | 0 |
| Violeta Patisserie | Pastelería | 1 | 0 | 4 | 0 |
| Bonheur Keto Patisserie | Pastelería | 2 | 2 | 2 | 0 |
| BuganVilla cafe & market | Tienda de delicatessen | 2 | 2 | 0 | 0 |
| Café Kanela | Cafetería | 2 | 0 | 2 | 0 |
| Pastelería Kleine Nuss | Pastelería | 2 | 0 | 5 | 1 |
| COMERCIAL RAKKO | Tienda de alimentos naturales | 3 | 3 | 0 | 0 |
| Gusto's - Keto, health & gluten free | Restaurante de comida sin gluten | 3 | 0 | 2 | 0 |
| Pizzeria Latinoamericana | Pizzería a domicilio | 3 | 3 | 0 | 0 |
| Productos El Pueblo | Panadería | 4 | 4 | 0 | 0 |
| B Fresh | Cafetería | 5 | 0 | 1 | 1 |
| Rebelde Pastelería Keto | Pastelería | 5 | 5 | 1 | 0 |
| Yoko Sea Food | Restaurante peruano | 6 | 6 | 0 | 0 |
| Biomercado Sin Gluten | Tienda de alimentación | 8 | 0 | 0 | 0 |
| Bonheur Pâtisserie | Pastelería | 8 | 8 | 9 | 1 |
| Crumbless Gluten Free Bakery | Restaurante de comida sin gluten | 8 | 0 | 0 | 0 |

## 5. Precios incompletos (<50% de platos con precio)

| name | cat | dishes | prices | review | rejected |
|---|---|---|---|---|---|
| Goût Gluten Free | Cafetería | 51 | 0 | 6 | 0 |
| Cetortillas - Low Carb Factory | Tortillería | 20 | 0 | 7 | 7 |
| Sapiens | Restaurante vegano | 18 | 0 | 7 | 0 |
| Biomercado Sin Gluten | Tienda de alimentación | 8 | 0 | 0 | 0 |
| Crumbless Gluten Free Bakery | Restaurante de comida sin gluten | 8 | 0 | 0 | 0 |
| B Fresh | Cafetería | 5 | 0 | 1 | 1 |
| Gusto's - Keto, health & gluten free | Restaurante de comida sin gluten | 3 | 0 | 2 | 0 |
| Café Kanela | Cafetería | 2 | 0 | 2 | 0 |
| Pastelería Kleine Nuss | Pastelería | 2 | 0 | 5 | 1 |
| Emporio de la Tierra | Tienda de alimentos naturales | 1 | 0 | 0 | 0 |
| Las Petunias Pastelería sin azúcar y sin gluten | Pastelería | 1 | 0 | 1 | 0 |
| Violeta Patisserie | Pastelería | 1 | 0 | 4 | 0 |
| L'Arrabbiata Foodmarket | Supermercado | 13 | 1 | 3 | 0 |
| CASACIENCAFE | Snack bar | 50 | 9 | 9 | 1 |
| Alma Chilanga | Restaurante mexicano | 24 | 5 | 15 | 9 |
| Pizza Bistrot | Restaurante | 24 | 8 | 2 | 2 |
| Piegari Chile | Restaurante italiano | 21 | 7 | 9 | 1 |

## 6. Mucho ruido de extracción (revisión + rechazados >= 20)

| name | cat | dishes | review | rejected |
|---|---|---|---|---|
| Sin Culpa Market | Tienda de alimentos naturales | 499 | 54 | 6 |
| Dulces aplv | Pastelería | 222 | 40 | 0 |
| Alma Chilanga | Restaurante mexicano | 24 | 15 | 9 |
| Patagonia Schokoland | Heladería | 21 | 21 | 0 |

## 7. Sin ningún dato

- Glutón (Sin categoría)
- Mercado Condell (Centro comercial)
- Montenegro 391 (Sin categoría)
- Mr Foodie (Supermercado)

