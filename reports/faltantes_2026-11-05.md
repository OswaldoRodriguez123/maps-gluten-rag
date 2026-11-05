# Restaurantes con poca data — después de P0

_Fecha: 2026-11-05 · Fuente: Doc regenerado con normalización P0_

## Resumen

- **100 lugares** en la lista.
- **64 con platos publicables**: 2380 platos.
- **1 solo con categorías** (sin platos específicos).
- **35 sin carta ni categorías**: 15 sin web y 20 con web.
- **14 con carta corta** (1-9 platos).
- **25 con menos del 50% de precios**.
- **23 con mucho ruido** (revisión + rechazados >= 20).
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
| ALLFREE | Tienda de alimentos naturales | 10 | 0 | 0 | 0 | https://www.allfree.cl/ |
| Light Marías | Restaurante de comida sin gluten | 10 | 6 | 0 | 0 | http://www.lightmarias.cl/ |
| Thani Gluten Free | Pastelería | 9 | 3 | 0 | 0 | https://www.thani.cl/ |
| Pastelería La Celeste | Pastelería | 8 | 5 | 0 | 0 | http://www.pastelerialaceleste.cl/ |
| Massanoglutenfree | Pastelería | 7 | 2 | 0 | 0 | http://www.massanoglutenfree.cl/ |
| BuganVilla cafe & market | Tienda de delicatessen | 6 | 1 | 0 | 0 | http://www.buganvilla.cl/ |
| COMERCIAL RAKKO | Tienda de alimentos naturales | 5 | 0 | 0 | 0 | https://www.rakkonatural.cl/ |
| Libre Punto SpA | Tienda de alimentos naturales | 4 | 0 | 0 | 0 | http://www.librepunto.cl/ |
| Fain | Tienda de alimentos naturales | 3 | 0 | 0 | 0 | http://www.fain.cl/ |
| Mercadito sano y natural | Tienda de alimentos naturales | 2 | 0 | 0 | 0 | http://www.mercaditosyn.cl/ |
| Popolo Pizza sin Gluten | Pizzería a domicilio | 2 | 1 | 0 | 0 | http://www.popolo.cl/ |
| Productos El Pueblo | Panadería | 2 | 3 | 0 | 0 | https://www.productoselpueblo.cl/ |
| Dulces aplv | Pastelería | 1 | 2 | 0 | 0 | https://dulcesaplv.com/ |
| Pizzeria Latinoamericana | Pizzería a domicilio | 1 | 4 | 0 | 0 | https://www.pizzerialatinoamericana.com/ |
| Sin Culpa Market | Tienda de alimentos naturales | 1 | 0 | 0 | 0 | https://www.sinculpamarket.cl/ |
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
| Las Petunias Pastelería sin azúcar y sin gluten | Pastelería | 1 | 0 | 1 | 0 |
| Violeta Patisserie | Pastelería | 1 | 0 | 4 | 0 |
| Bonheur Keto Patisserie | Pastelería | 2 | 2 | 2 | 0 |
| Café Kanela | Cafetería | 2 | 0 | 2 | 0 |
| Pastelería Kleine Nuss | Pastelería | 2 | 0 | 5 | 1 |
| Gusto's - Keto, health & gluten free | Restaurante de comida sin gluten | 3 | 0 | 2 | 0 |
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
| Cetortillas - Low Carb Factory | Tortillería | 20 | 0 | 8 | 6 |
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
| Magnolia | Restaurante | 12 | 1 | 12 | 8 |
| TastyFree | Panadería | 17 | 2 | 13 | 10 |
| CASACIENCAFE | Snack bar | 50 | 9 | 9 | 1 |
| Alma Chilanga | Restaurante mexicano | 24 | 5 | 15 | 9 |
| Pizza Bistrot | Restaurante | 26 | 6 | 18 | 14 |
| Fortunata | Tienda de pasta | 29 | 7 | 19 | 10 |
| Tremus Las Condes Market & Coffee | Pastelería | 34 | 10 | 38 | 20 |
| Piegari Chile | Restaurante italiano | 21 | 7 | 9 | 1 |
| Café Bicka | Cafetería | 41 | 14 | 27 | 16 |
| Sicily Pizza, Gelato e Caffe | Pizzería | 32 | 12 | 23 | 9 |
| Sushi y Pasteleria Dos Polos | Restaurante de comida sin gluten | 12 | 5 | 21 | 21 |
| Restaurant La Escalera | Restaurante | 31 | 15 | 20 | 12 |

## 6. Mucho ruido de extracción (revisión + rechazados >= 20)

| name | cat | dishes | review | rejected |
|---|---|---|---|---|
| Quinoa | Restaurante vegetariano | 97 | 118 | 83 |
| NAOKI | Restaurante japonés | 79 | 54 | 50 |
| Je Suis Raclette \| MUT | Restaurante suizo | 53 | 59 | 32 |
| Restoran Pinpilinpausha | Restaurante de cocina española | 51 | 58 | 20 |
| Dónde El Guatón | Restaurante chileno | 59 | 44 | 28 |
| Lemongrass | Restaurante asiático | 55 | 45 | 17 |
| Lynn Café \| Tostaduría y Cafetería de Café de Especialidad en Santiago | Cafetería | 39 | 42 | 18 |
| P.F. Chang's | Restaurante asiático | 27 | 43 | 17 |
| QUIMEY SUSHI FUSION & GLUTEN FREE | Restaurante de comida sin gluten | 58 | 41 | 19 |
| Tremus Las Condes Market & Coffee | Pastelería | 34 | 38 | 20 |
| Piaf Café | Cafetería | 86 | 40 | 10 |
| José & José Tiendita de Café | Cafetería | 12 | 30 | 15 |
| Café Bicka | Cafetería | 41 | 27 | 16 |
| Panart® | Pastelería | 54 | 32 | 11 |
| Sushi y Pasteleria Dos Polos | Restaurante de comida sin gluten | 12 | 21 | 21 |
| Patagonia Schokoland | Heladería | 15 | 12 | 21 |
| Pizza Bistrot | Restaurante | 26 | 18 | 14 |
| Restaurant La Escalera | Restaurante | 31 | 20 | 12 |
| Sicily Pizza, Gelato e Caffe | Pizzería | 32 | 23 | 9 |
| Fortunata | Tienda de pasta | 29 | 19 | 10 |
| Alma Chilanga | Restaurante mexicano | 24 | 15 | 9 |
| TastyFree | Panadería | 17 | 13 | 10 |
| Magnolia | Restaurante | 12 | 12 | 8 |

## 7. Sin ningún dato

- Glutón (Sin categoría)
- Mercado Condell (Centro comercial)
- Montenegro 391 (Sin categoría)
- Mr Foodie (Supermercado)

