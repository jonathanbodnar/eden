"""Ingest batch 3 of visual library: additional settlements, pyramids, temples."""
import asyncio
import hashlib
import json
import logging

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ARTIFACTS = [
    # === ANATOLIA EARLY ===
    {"title": "Hallan Çemi Settlement", "location": "Batman, Turkey", "culture": "Epi-Palaeolithic / Early Neolithic", "region": "Anatolia", "date_start": -11000, "date_end": -10000, "date_label": "~11,000 BCE",
     "description": "A small semi-sedentary settlement on the banks of the Batman River in southeastern Turkey. The site contains circular pit-dwellings approximately 2–4 meters in diameter, dug into the ground and lined with stone. Excavated features include sandstone grinding slabs, pestles, and large quantities of wild sheep and pig bones. A communal open area with a large stone mortar and possible feasting debris occupies the center of the settlement. The site is one of the earliest known villages in the Upper Tigris region, predating agricultural cultivation."},

    {"title": "Körtik Tepe Settlement", "location": "Turkey", "culture": "Epi-Palaeolithic / Proto-Neolithic", "region": "Anatolia", "date_start": -10000, "date_end": -9000, "date_label": "~10,000 BCE",
     "description": "A settlement mound on the upper Tigris River near the Batman-Tigris confluence. The site features round and oval semi-subterranean structures with stone foundations and plastered floors. Over 400 burials were found beneath dwelling floors, many accompanied by carved stone vessels, bone tools, and chlorite bracelets. Decorated stone bowls with incised geometric and animal motifs are among the earliest known examples of carved stone art in the region. Subsistence was based on hunting, fishing, and wild plant gathering."},

    {"title": "Boncuklu Tarla Ritual Site", "location": "Mardin, Turkey", "culture": "Pre-Pottery Neolithic", "region": "Anatolia", "date_start": -10000, "date_end": -7500, "date_label": "~10,000 BCE",
     "description": "A Pre-Pottery Neolithic site in Mardin province featuring both domestic and ritual architecture. Rectangular and curvilinear buildings with terrazzo-like lime-plaster floors have been excavated. Several structures contain T-shaped and obelisk-shaped stone pillars set into the walls and floors, stylistically similar to those at Göbekli Tepe. Large quantities of stone beads (boncuk means 'bead' in Turkish) were recovered, giving the site its name. The site shows evidence of early plant cultivation alongside continued reliance on wild resources."},

    {"title": "Çayönü Tepesi Settlement", "location": "Diyarbakır, Turkey", "culture": "Pre-Pottery Neolithic", "region": "Anatolia", "date_start": -10000, "date_end": -7000, "date_label": "~10,000–7000 BCE",
     "description": "A long-occupied settlement near the Tigris headwaters showing a clear architectural evolution over 3,000 years. The earliest phase contains round huts with stone foundations; later phases transition to rectangular buildings with grid-plan stone foundations ('grill buildings'), channeled buildings, cobble-paved buildings, and finally large cell-plan structures. A 'Skull Building' contained over 70 human skulls and a large polished stone slab stained with blood residue. The site yielded some of the earliest evidence of copper working, including native copper pins and hooks."},

    # === LEVANT ===
    {"title": "Tell Qaramel Towers", "location": "Syria", "culture": "Pre-Pottery Neolithic A", "region": "Levant", "date_start": -10500, "date_end": -9000, "date_label": "~10,500 BCE",
     "description": "A settlement mound north of Aleppo containing at least five circular stone towers dating to the 11th millennium BCE. The towers are built of roughly dressed limestone blocks and stand up to 6 meters in preserved height, making them among the oldest known freestanding stone towers in the world. Domestic structures at the site are circular with stone foundations and mud-brick superstructures. Excavations revealed communal storage facilities and evidence of early cereal cultivation. The towers predate the famous tower at Jericho by approximately two millennia."},

    # === EARLY SETTLEMENTS ===
    {"title": "Jarmo Settlement", "location": "Iraq", "culture": "Early Neolithic", "region": "Mesopotamia", "date_start": -7000, "date_end": -6000, "date_label": "~7000 BCE",
     "description": "A small agricultural village in the foothills of the Zagros Mountains in northeastern Iraq. The site covers approximately 1.3 hectares and contains roughly 25 mud-walled houses with stone foundations arranged in clusters. Reed-matting impressions are preserved in mud plaster on walls and floors. Inhabitants cultivated emmer wheat, two-row barley, and lentils, and kept domesticated goats, sheep, and pigs. Stone tools include obsidian blades traded from sources over 300 km away. Excavated by Robert Braidwood between 1948 and 1955."},

    {"title": "Ali Kosh Settlement", "location": "Iran", "culture": "Early Neolithic", "region": "Zagros", "date_start": -7000, "date_end": -5500, "date_label": "~7000 BCE",
     "description": "A low mound site on the Deh Luran plain in southwestern Iran. The earliest occupation level (Bus Mordeh phase) consists of small semi-permanent structures of sun-dried mud-brick slabs. Botanical remains include wild and early-cultivated emmer wheat, barley, and lentils, representing some of the earliest farming in the Zagros lowlands. Faunal remains are dominated by wild gazelle and onager in early levels, with domesticated goats appearing in later phases. The site provides a key sequence for tracking the transition from foraging to agriculture in the Near East."},

    {"title": "Mehrgarh Settlement", "location": "Pakistan", "culture": "Early Neolithic", "region": "South Asia", "date_start": -7000, "date_end": -2500, "date_label": "~7000 BCE",
     "description": "A large Neolithic to Chalcolithic settlement at the foot of the Bolan Pass in Baluchistan. The earliest levels (Period I) contain small mud-brick compartmented buildings used for storage and burial, with reed structures for habitation. Inhabitants cultivated barley, wheat, and dates, and herded cattle, sheep, and goats. Burials include grave goods of shell, turquoise, and lapis lazuli beads, indicating long-distance trade networks. The site is the earliest known farming settlement in South Asia and shows continuous occupation for over 4,000 years across seven major periods."},

    # === MESOPOTAMIA ADDITIONAL ===
    {"title": "Mari Palace Complex", "location": "Syria", "culture": "Amorite / Old Babylonian", "region": "Mesopotamia", "date_start": -1800, "date_end": -1760, "date_label": "~1800 BCE",
     "description": "A massive mudbrick palace covering approximately 2.5 hectares on the middle Euphrates River. The complex contained over 300 rooms organized around multiple courtyards, including throne rooms, administrative offices, workshops, kitchens, and a royal archive of over 25,000 cuneiform tablets. Wall paintings in the Court of the Palms depict investiture scenes with deities and processions of tribute-bearers in vivid polychrome. The palace had an elaborate plumbing system with terracotta pipes and bathing rooms. It was destroyed by Hammurabi of Babylon around 1761 BCE."},

    {"title": "Ebla City Ruins", "location": "Syria", "culture": "Early Bronze Age / Eblaite", "region": "Levant", "date_start": -2500, "date_end": -2300, "date_label": "~2500 BCE",
     "description": "An ancient city mound (Tell Mardikh) in northwestern Syria covering approximately 56 hectares. The site features a lower city surrounded by massive earthen ramparts with a stone-lined gate, and an upper acropolis with a royal palace complex. Palace G on the acropolis yielded an archive of nearly 17,000 cuneiform tablets written in Sumerian and Eblaite, documenting trade, diplomacy, and administration. The palace contained large storage areas with carbonized grain and crushed lapis lazuli. The city was destroyed by either Sargon of Akkad or his grandson Naram-Sin."},

    {"title": "Dur-Kurigalzu Ziggurat", "location": "Iraq", "culture": "Kassite Babylonian", "region": "Mesopotamia", "date_start": -1400, "date_end": -1225, "date_label": "~1400 BCE",
     "description": "A massive mudbrick ziggurat standing approximately 57 meters tall in its current ruined state, located near modern Baghdad. Built by the Kassite king Kurigalzu I as the centerpiece of a new capital city. The core is constructed of sun-dried mudbrick reinforced with layers of reed matting and rope at regular intervals, a technique that has contributed to its remarkable preservation. The surrounding palace complex contained painted wall decorations and terracotta figurines. Reed-rope reinforcement layers are clearly visible in the eroded facade of the tower."},

    {"title": "Hatra Temple Complex", "location": "Iraq", "culture": "Parthian / Arab-Mesopotamian", "region": "Mesopotamia", "date_start": -200, "date_end": 240, "date_label": "~200 BCE",
     "description": "A fortified circular city approximately 2 km in diameter, enclosed by double walls with towers and a moat. The central temenos (sacred precinct) contains large stone temples combining Mesopotamian, Greek, and Roman architectural elements with barrel-vaulted iwans (arched halls). The Great Temple features carved stone masks and decorative friezes depicting eagles, gorgon heads, and divine figures. Columns, pilasters, and arches use Hellenistic orders adapted to local style. The city withstood two sieges by Roman emperor Trajan (116 CE) and Septimius Severus (198 CE) before its destruction by the Sasanian king Shapur I around 241 CE."},

    # === EGYPT ADDITIONAL ===
    {"title": "Meidum Pyramid", "location": "Egypt", "culture": "Old Kingdom Egyptian (3rd–4th Dynasty)", "region": "Egypt", "date_start": -2600, "date_end": -2580, "date_label": "~2600 BCE",
     "description": "A partially collapsed pyramid originally built as a step pyramid in seven or eight stages, then modified to a true pyramid with smooth limestone casing. The current appearance is a three-stepped tower rising from a mound of debris, giving it a distinctive ruined profile. The pyramid stands approximately 65 meters tall and was begun under Huni (last king of the 3rd Dynasty) and completed or modified by Sneferu. An internal descending passage leads to a corbelled burial chamber at ground level. A small mortuary temple and a causeway remain on the east face."},

    {"title": "Bent Pyramid (Sneferu)", "location": "Dahshur, Egypt", "culture": "Old Kingdom Egyptian (4th Dynasty)", "region": "Egypt", "date_start": -2600, "date_end": -2580, "date_label": "~2600 BCE",
     "description": "A pyramid with a distinctive change in angle partway up its faces, rising at 54 degrees for the lower section and then shifting to 43 degrees for the upper portion. The structure stands approximately 101 meters tall with a base length of 188 meters. It retains a substantial amount of its original smooth Tura limestone casing, making it the best-preserved pyramid exterior in Egypt. The pyramid contains two separate internal chamber systems accessed from the north and west faces, with corbelled ceilings. Cedar beams installed as structural supports during construction are still in place inside."},

    {"title": "Red Pyramid", "location": "Dahshur, Egypt", "culture": "Old Kingdom Egyptian (4th Dynasty)", "region": "Egypt", "date_start": -2600, "date_end": -2575, "date_label": "~2600 BCE",
     "description": "The first successfully completed true pyramid, standing approximately 104 meters tall with a consistent slope of 43 degrees. Named for the reddish hue of its exposed limestone core blocks after the white Tura limestone casing was removed in antiquity. The base measures 220 meters per side. Three internal corbelled chambers are accessed by a descending passage on the north face; the final chamber is set high above the floor, reached by a short ascending passage. Construction marks painted on blocks include dates from Sneferu's reign. It is the third-largest pyramid in Egypt after Khufu and Khafre."},

    {"title": "Serapeum of Saqqara", "location": "Egypt", "culture": "New Kingdom through Ptolemaic Egyptian", "region": "Egypt", "date_start": -1400, "date_end": -30, "date_label": "~1400 BCE+",
     "description": "An underground burial complex for the sacred Apis bulls, consisting of rock-cut tunnels extending over 350 meters beneath the Saqqara plateau. The main gallery contains 24 massive granite and basalt sarcophagi, each weighing approximately 60–80 tons, with lids weighing an additional 20–30 tons. The sarcophagi are precision-cut and polished, set into alcoves carved into the tunnel walls. Earlier burials (18th Dynasty) were in separate chambers with wooden coffins. Auguste Mariette discovered and cleared the galleries in 1851. Votive stelae left by pilgrims line the approach corridor."},

    {"title": "Deir el-Medina Worker Village", "location": "Egypt", "culture": "New Kingdom Egyptian", "region": "Egypt", "date_start": -1500, "date_end": -1070, "date_label": "~1500 BCE",
     "description": "A planned settlement of approximately 70 stone-and-mudbrick houses arranged along a central street, enclosed by a perimeter wall, on the west bank at Thebes. The village housed the craftsmen and laborers who built the royal tombs in the Valley of the Kings. Houses follow a standard layout: a front room with built-in altar, a main room with raised platform and column, a kitchen with oven at the rear, and underground cellar storage. Thousands of inscribed ostraca (limestone flakes and pottery sherds) found here record daily life, work schedules, disputes, and medical remedies."},

    # === INDUS ADDITIONAL ===
    {"title": "Rakhigarhi Settlement", "location": "India", "culture": "Indus Valley Civilization", "region": "Indus", "date_start": -2600, "date_end": -1900, "date_label": "~2600 BCE",
     "description": "One of the largest Indus Valley Civilization sites, covering approximately 350 hectares across several mounds in Haryana, India. The settlement includes a fortified area with mudbrick walls and bastions, and a lower town with planned streets, brick-lined drains, and standardized house plans. Excavations have revealed fire altars, terracotta figurines, steatite seals with Indus script, and evidence of bead-making workshops. Burials at the site include extended inhumations with pottery vessels and personal ornaments. The scale of the site rivals or exceeds Mohenjo-daro and Harappa."},

    {"title": "Kalibangan Fire Altars", "location": "India", "culture": "Indus Valley Civilization", "region": "Indus", "date_start": -2500, "date_end": -1900, "date_label": "~2500 BCE",
     "description": "A fortified Indus Valley site on the dried-up Ghaggar-Hakra River in Rajasthan. The site is divided into a citadel mound and a lower town, both surrounded by mudbrick fortification walls. The citadel contains a row of fire altars — raised mudbrick platforms with fire pits, ash, and charred animal bones — arranged in a north-south line, suggesting organized ritual activity. The lower town has a grid-plan street layout with houses containing standardized bathing platforms and drains. The earliest level (pre-Indus, c. 3000 BCE) preserves a plowed field with two sets of furrows at right angles."},

    # === INDIA ===
    {"title": "Udayagiri Caves", "location": "India", "culture": "Gupta Empire", "region": "India", "date_start": -200, "date_end": 400, "date_label": "~200 BCE",
     "description": "A group of 20 rock-cut caves carved into a sandstone hillside near Vidisha in Madhya Pradesh. The caves include both Hindu and Jain shrines, with the most prominent being Cave 5, which contains a monumental carved panel of Vishnu in his Varaha (boar) incarnation rescuing the earth goddess, measuring over 4 meters tall. Cave 1 is a Jain cave with carved figures of tirthankaras. Several caves feature inscriptions from the reign of Chandragupta II (c. 380–415 CE). The site also includes structural remains of a Gupta-period temple platform on the hilltop and an astronomical rock-cut passage aligned to the summer solstice."},

    # === CHINA ADDITIONAL ===
    {"title": "Erlitou Palace Complex", "location": "China", "culture": "Erlitou Culture / Early Xia or Shang", "region": "China", "date_start": -1900, "date_end": -1500, "date_label": "~1900 BCE",
     "description": "A large-scale palatial complex at Erlitou in Henan province, considered a possible capital of the Xia dynasty. Palace Foundation 1 is a rammed-earth platform measuring approximately 108 x 100 meters, supporting a timber-framed hall surrounded by covered corridors and enclosing a large courtyard. Palace Foundation 2 is a slightly smaller complex with a similar layout. The site has yielded China's earliest known bronze ritual vessels, jade and turquoise artifacts, and a turquoise-inlaid bronze plaque in the shape of a dragon. A network of roads and a possible city wall have been identified across the 300-hectare site."},

    {"title": "Taosi Observatory Site", "location": "China", "culture": "Longshan / Early Chinese", "region": "China", "date_start": -2300, "date_end": -1900, "date_label": "~2300 BCE",
     "description": "A large walled settlement of approximately 280 hectares in Shanxi province containing what may be China's oldest astronomical observatory. The observatory structure is a rammed-earth platform with a semicircular series of rammed-earth pillars creating narrow slits through which sunrise positions could be observed throughout the year. The site also contains a large rammed-earth palatial compound, elite burials with jade and lacquerware, a possible ritual/sacrificial area, and evidence of craft specialization including copper smelting. Astronomical observations from the slit structure align with solstice and equinox sunrise positions."},

    {"title": "Yinxu Royal Tomb Complex", "location": "Anyang, China", "culture": "Shang Dynasty", "region": "China", "date_start": -1200, "date_end": -1050, "date_label": "~1200 BCE",
     "description": "The royal cemetery of the late Shang dynasty capital at Anyang in Henan province. The complex contains large cruciform-shaped underground tombs accessed by four long ramps oriented to the cardinal directions. Tomb M1001, the largest, measures approximately 19 x 14 meters at the base and 12 meters deep. Tombs contained bronze ritual vessels, jade objects, chariots with horses, and sacrificial victims numbering in the hundreds. The nearby tomb of Lady Fu Hao (M5), found intact, yielded over 440 bronze objects, 590 jade pieces, and 6,900 cowrie shells. Oracle bone inscriptions found in storage pits at the site document Shang divination practices."},

    # === AEGEAN ADDITIONAL ===
    {"title": "Phaistos Palace", "location": "Crete", "culture": "Minoan", "region": "Minoan", "date_start": -1900, "date_end": -1400, "date_label": "~1900 BCE",
     "description": "A Minoan palatial complex on a hilltop in south-central Crete overlooking the Mesara Plain. The palace is organized around a central court (46 x 22 meters) with a grand staircase on the west side, storage magazines, and cult rooms. The west court features raised processional walkways and a theatrical area with tiered seating. Architectural elements include light wells, pier-and-door partitions, and polythyron halls with multiple doorways. The famous Phaistos Disc, a fired clay disc stamped with undeciphered symbols, was found in the palace deposits. The first palace was destroyed around 1700 BCE and rebuilt on a larger scale."},

    {"title": "Malia Palace", "location": "Crete", "culture": "Minoan", "region": "Minoan", "date_start": -1900, "date_end": -1450, "date_label": "~1900 BCE",
     "description": "A Minoan palace on the north coast of Crete, smaller and less elaborately decorated than Knossos but well-preserved in plan. The complex covers approximately 7,500 square meters arranged around a central court (48 x 23 meters) with a kernos stone (a circular stone offering table with 34 small hollows) at the southwest corner. The palace includes storage magazines with large pithoi, a hypostyle crypt with central pillar, and residential quarters. A gold bee pendant depicting two bees depositing a drop of honey, found in the nearby Chrysolakkos burial complex, is one of the finest examples of Minoan goldwork."},

    {"title": "Pergamon Acropolis", "location": "Turkey", "culture": "Hellenistic Greek / Attalid Dynasty", "region": "Greek", "date_start": -300, "date_end": -100, "date_label": "~300 BCE",
     "description": "A dramatic hilltop citadel rising 335 meters above the Caicus River plain in western Turkey. The acropolis features terraced construction on steep slopes, including the steepest theater in the ancient world (80 rows of seats carved into the hillside, seating 10,000). The Great Altar of Zeus (now reconstructed in the Pergamon Museum, Berlin) was a monumental U-shaped platform with a 113-meter-long sculptured frieze depicting the battle of gods and giants. The acropolis also includes the Library of Pergamon (said to hold 200,000 scrolls), royal palaces, temples to Athena and Trajan, arsenals, and extensive cisterns for water storage."},

    # === ITALY ===
    {"title": "Etruscan Necropolis of Tarquinia", "location": "Italy", "culture": "Etruscan", "region": "Italy", "date_start": -600, "date_end": -200, "date_label": "~600 BCE",
     "description": "A vast underground cemetery of rock-cut chamber tombs carved into a limestone plateau northwest of Rome. Over 6,000 tombs have been identified, of which approximately 200 contain painted wall frescoes in vivid colors depicting banquets, musicians, dancers, athletes, hunting scenes, and funerary rituals. The Tomb of the Leopards features reclining banqueters with wreaths and drinking cups beneath spotted leopards. The Tomb of the Augurs shows wrestlers and a figure interpreted as an umpire beside a painted false door. The frescoes, dating from the 6th to 2nd centuries BCE, provide the most extensive surviving record of Etruscan painting."},

    {"title": "Cerveteri Necropolis", "location": "Italy", "culture": "Etruscan", "region": "Italy", "date_start": -600, "date_end": -200, "date_label": "~600 BCE",
     "description": "The Banditaccia necropolis at Cerveteri covers approximately 400 hectares and contains thousands of tombs spanning the 9th through 2nd centuries BCE. The most distinctive tombs are circular tumuli — large circular mounds of earth over carved rock-cut chambers that imitate domestic architecture with carved doorways, roof beams, columns, and furniture rendered in stone. The Tomb of the Reliefs features stucco wall reliefs of household objects including shields, tools, cooking utensils, and pets. Tombs are arranged along regular streets forming a planned 'city of the dead.' The sarcophagus of the married couple (Sarcofago degli Sposi) was found here."},

    {"title": "Ostia Antica", "location": "Italy", "culture": "Roman", "region": "Italy", "date_start": -400, "date_end": 500, "date_label": "~400 BCE",
     "description": "The ancient port city of Rome at the mouth of the Tiber River, covering approximately 150 hectares of excavated ruins. The city features well-preserved multi-story apartment buildings (insulae) rising 3–4 stories, commercial bakeries with millstones and ovens, a theater seating 4,000, public baths with mosaic floors, warehouses (horrea) for grain storage, and the Piazzale delle Corporazioni — a commercial square with 61 offices identified by mosaic trade emblems on the pavement. The city's street grid, water system, and sewer network are largely intact. Population at peak was approximately 50,000–100,000 inhabitants."},

    # === MESOAMERICA ADDITIONAL ===
    {"title": "El Mirador", "location": "Guatemala", "culture": "Preclassic Maya", "region": "Mesoamerica", "date_start": -600, "date_end": 100, "date_label": "~600 BCE",
     "description": "A massive Preclassic Maya city in the Petén jungle of northern Guatemala. The site features the La Danta pyramid complex, which rises approximately 72 meters from the forest floor on a natural hill and has a total volume exceeding 2.8 million cubic meters — making it one of the largest pyramids by volume in the ancient world. The El Tigre pyramid complex stands approximately 55 meters tall. The two complexes are connected by a raised causeway. Stucco facade sculptures depicting Maya deities have been found on building facades. The city was a major center of the Preclassic period before being largely abandoned by 150 CE."},

    {"title": "Nakbé", "location": "Guatemala", "culture": "Middle Preclassic Maya", "region": "Mesoamerica", "date_start": -1000, "date_end": -200, "date_label": "~1000 BCE",
     "description": "One of the earliest large Maya settlements, located in the Mirador Basin of the Petén lowlands. The site contains monumental stone architecture dating to the Middle Preclassic period, including pyramidal platforms up to 45 meters tall. An elevated causeway (sacbe) connects Nakbé to the nearby site of El Mirador, approximately 13 km away. Architectural platforms are faced with cut limestone blocks and coated in thick lime plaster. The site shows early evidence of Maya monumental construction traditions including triadic pyramid groups — a large central pyramid flanked by two smaller structures on a shared basal platform."},

    {"title": "Kaminaljuyu", "location": "Guatemala", "culture": "Preclassic to Classic Maya", "region": "Mesoamerica", "date_start": -800, "date_end": 900, "date_label": "~800 BCE",
     "description": "A large highland Maya site now largely buried beneath modern Guatemala City, originally covering approximately 5 square kilometers. The site contained over 200 earthen platforms and mounds, a hydraulic system of canals and reservoirs, and elaborate tombs with jade, obsidian, and pyrite mirror offerings. Mound constructions used puddled adobe clay rather than stone. The site controlled the El Chayal obsidian source and was a major trade center. During the Early Classic period, Teotihuacan-style talud-tablero architecture and green obsidian imports indicate strong central Mexican influence or direct contact."},

    {"title": "Cuicuilco Pyramid", "location": "Mexico", "culture": "Preclassic Mesoamerican", "region": "Mesoamerica", "date_start": -800, "date_end": -200, "date_label": "~800–200 BCE",
     "description": "A large circular stepped pyramid in the southern Basin of Mexico, partially buried by the Xitle volcano's lava flow. The structure is a truncated cone approximately 20 meters tall with a base diameter of 110 meters, built of rubble fill faced with stone. A ramp on the east side leads to the summit platform, which held an altar. It is one of the oldest monumental structures in the Basin of Mexico and may have been the dominant center in the valley before the eruption (c. 200–400 CE) destroyed the surrounding settlement. An excavated altar on the summit retained traces of red pigment."},

    {"title": "Tula (Early Toltec Precursor Phase)", "location": "Mexico", "culture": "Epiclassic / Early Toltec", "region": "Mesoamerica", "date_start": -200, "date_end": 200, "date_label": "~200 BCE+",
     "description": "The site of Tula Grande in Hidalgo, Mexico, which later became the Toltec capital, shows evidence of early occupation and construction predating the Toltec florescence. The earliest architectural phases include modest residential platforms and small temple bases of adobe and rubble-core construction. A ball court from this early period has been partially excavated. The site is situated on a limestone ridge overlooking the Tula River, a strategic position controlling routes between the Basin of Mexico and regions to the north. Later monumental construction (c. 900–1150 CE) including the famous Atlantean warrior columns was built over these earlier foundations."},

    # === SOUTH AMERICA ADDITIONAL ===
    {"title": "Sechin Bajo Complex", "location": "Peru", "culture": "Early Formative / Preceramic", "region": "South America", "date_start": -3500, "date_end": -1500, "date_label": "~3500 BCE",
     "description": "A monumental complex in the Casma Valley of coastal Peru containing one of the oldest known plazas in the Americas. The earliest construction phase features a circular sunken plaza approximately 10–12 meters in diameter with stone-faced walls, radiocarbon-dated to approximately 3500 BCE. Later phases added rectangular stone-faced platforms and additional plazas. The site is part of the larger Sechín complex that includes Cerro Sechín and Sechín Alto. Adobe and stone construction techniques are both present. The site demonstrates that monumental communal architecture in the Americas began in the preceramic period."},

    {"title": "Sechin Alto Complex", "location": "Peru", "culture": "Early Formative", "region": "South America", "date_start": -1800, "date_end": -900, "date_label": "~1800 BCE",
     "description": "A massive platform mound in the Casma Valley of Peru, measuring approximately 300 x 250 meters at the base and standing about 44 meters tall — one of the largest structures in the ancient New World by volume. The mound is constructed of stone fill with stone-faced terraced walls. A linear arrangement of plazas, sunken circular courts, and smaller platforms extends approximately 1.4 km from the main mound. The complex was built in multiple construction phases using granite boulders and river cobbles set in mud mortar. No carved stone decoration has been found on the structure."},

    {"title": "Kotosh Temple (Temple of the Crossed Hands)", "location": "Peru", "culture": "Preceramic / Early Formative", "region": "South America", "date_start": -2000, "date_end": -1500, "date_label": "~2000 BCE",
     "description": "A preceramic temple site in the highlands of central Peru near Huánuco. The most famous feature is a small chamber (approximately 9 square meters) with a pair of crossed human forearms and hands modeled in unfired clay relief on the wall below a niche, giving the temple its name. The chamber has a central fire pit for ritual burning. Multiple superimposed temple platforms were built in a tradition of ritual construction, burial, and rebuilding. The site demonstrates the 'Kotosh Religious Tradition' of small ceremonial chambers with hearths and offerings, found at several early highland and coastal Peruvian sites."},

    {"title": "Huaca de la Luna", "location": "Peru", "culture": "Moche", "region": "Moche", "date_start": -100, "date_end": 600, "date_label": "~100 BCE+",
     "description": "A large adobe brick pyramid temple in the Moche Valley of northern Peru, standing approximately 21 meters tall and covering around 290 x 210 meters at the base. The structure was built in multiple phases, with new construction encasing older phases, preserving polychrome murals on earlier walls. Murals and relief friezes depict the Moche deity known as the 'Decapitator' or Ai Apaec with fanged mouth and radiating serpent headdress. Painted walls show procession scenes, combat, and prisoner sacrifice. Excavations in the plaza between Huaca de la Luna and Huaca del Sol revealed an urban zone with workshops, residences, and plazas."},

    {"title": "Huaca del Sol", "location": "Peru", "culture": "Moche", "region": "Moche", "date_start": -100, "date_end": 600, "date_label": "~100 BCE+",
     "description": "The largest solid adobe structure in the pre-Columbian Americas, originally standing approximately 50 meters tall with a base of roughly 340 x 160 meters. The pyramid was constructed using an estimated 143 million adobe bricks, many stamped with maker's marks identifying different labor groups. A stepped platform design with a large flat summit area likely served as the primary administrative and possibly residential center of the Moche capital. The western face was severely damaged by Spanish colonial treasure-seekers who diverted the Moche River to wash away the structure. The remaining cross-section reveals the internal construction phases."},

    {"title": "El Paraíso Complex", "location": "Peru", "culture": "Late Preceramic", "region": "South America", "date_start": -2000, "date_end": -1500, "date_label": "~2000 BCE",
     "description": "A monumental preceramic complex at the mouth of the Chillón River valley near Lima, Peru. The site consists of at least nine large mounds arranged in a U-shaped configuration opening toward the river, enclosing a central plaza area. The main mound (Unit I) is a stone-and-mortar platform approximately 300 meters long and 8 meters tall. Construction used quarried stone blocks joined with clay mortar and plastered surfaces. The total estimated volume of construction material is approximately 100,000 cubic meters. No ceramics were found, but cotton textiles, gourds, and marine shell artifacts were recovered."},

    # === AFRICA ADDITIONAL ===
    {"title": "Great Enclosure (Great Zimbabwe)", "location": "Zimbabwe", "culture": "Kingdom of Zimbabwe (Shona)", "region": "Southern Africa", "date_start": 1100, "date_end": 1450, "date_label": "~1100 CE",
     "description": "The largest single ancient structure in sub-Saharan Africa, consisting of an elliptical enclosure wall approximately 255 meters in circumference, up to 11 meters high and 5 meters thick at the base. Constructed entirely of shaped granite blocks laid in courses without mortar using a technique of inward-leaning walls for stability. Inside the enclosure stands a solid conical tower approximately 5.5 meters in diameter and 9 meters tall, built of carefully coursed stonework. A narrow passage runs between the outer wall and an inner wall decorated along the top with a chevron pattern frieze. Daga (clay) hut foundations and artifact deposits indicate domestic occupation within the walls."},

    {"title": "Djenne-Djenno Urban Site", "location": "Mali", "culture": "West African Iron Age", "region": "West Africa", "date_start": -250, "date_end": 1400, "date_label": "~250 BCE",
     "description": "One of the oldest known urban centers in sub-Saharan Africa, located on a flood plain at the confluence of the Bani and Niger rivers. The settlement mound rises approximately 8 meters above the surrounding plain and covers about 33 hectares. Cylindrical mudbrick architecture was used for houses and walls from the earliest levels. Iron smelting evidence dates to the earliest occupation layers (c. 250 BCE). The site shows no evidence of centralized monumental architecture or elite segregation, suggesting a heterarchical (non-hierarchical) urban form. Excavations by Roderick and Susan McIntosh yielded terracotta figurines, copper ornaments, glass beads from long-distance trade, and evidence of rice cultivation."},

    {"title": "Tichitt Settlement Complex", "location": "Mauritania", "culture": "Tichitt-Walata Tradition", "region": "West Africa", "date_start": -2000, "date_end": -500, "date_label": "~2000 BCE",
     "description": "A complex of dry-stone walled settlement compounds along a cliff escarpment at the southern edge of the Sahara. Settlements consist of circular and sub-rectangular enclosures defined by dry-stone walls, organized into compounds and connected by pathways and corrals. The settlement hierarchy ranges from small single-compound hamlets to large aggregated villages of over 80 compounds. Stone-lined granary foundations indicate storage of cultivated pearl millet, representing some of the earliest evidence for African cereal agriculture. The settlements were progressively abandoned as the Sahara expanded southward during the late 2nd and 1st millennia BCE."},

    # === OCEANIA ADDITIONAL ===
    {"title": "Leluh Ruins (Kosrae)", "location": "Micronesia", "culture": "Saudeleur / Late Prehistoric Kosraean", "region": "Oceania", "date_start": 1200, "date_end": 1500, "date_label": "~1200 CE",
     "description": "A monumental basalt-walled complex on an artificial islet off the southeastern coast of Kosrae in the Caroline Islands. The ruins cover approximately 27 hectares and include royal compounds enclosed by massive walls of stacked prismatic basalt columns, some walls reaching 6 meters in height and 2 meters in thickness. Interior features include raised coral-rubble platforms, burial vaults, and canal channels for canoe access. The basalt logs used in construction weigh up to several tons each and were quarried from inland sources and transported to the coast. The complex served as the political and ceremonial center of the island's ruling chiefs."},

    {"title": "Taputapuātea Marae", "location": "French Polynesia", "culture": "Ancient Polynesian", "region": "Oceania", "date_start": 1000, "date_end": 1400, "date_label": "~1000 CE",
     "description": "A large stone temple platform (marae) on the island of Raiatea in the Society Islands, regarded as one of the most sacred sites in eastern Polynesia. The main ahu (stone platform) measures approximately 43 x 7 meters, constructed of large basalt and coral limestone blocks. The marae is part of a complex that includes multiple smaller platforms, paved courtyards, upright stone slabs (backrests for gods and chiefs), and associated residential and craft areas. The site served as a center for long-distance voyaging ceremonies and the worship of the god Oro. Oral traditions from across Polynesia reference Taputapuātea as a homeland and navigational origin point."},
]


async def main():
    pool = await asyncpg.create_pool(
        host="localhost", port=5432, user="eden", password="eden", database="eden",
        min_size=1, max_size=5,
    )

    async with pool.acquire() as conn:
        ts_id = await conn.fetchval("SELECT id FROM trusted_sources WHERE slug = 'wikidata-artifacts'")
        if not ts_id:
            ts_id = await conn.fetchval("SELECT id FROM trusted_sources ORDER BY created_at LIMIT 1")
        log.info("Using trusted_source_id: %s", ts_id)

    inserted = 0
    skipped = 0
    errors = 0

    for art in ARTIFACTS:
        ext_id = f"visual-lib-{art['title'].lower().replace(' ', '-').replace('/', '-')[:80]}"
        r2_key = f"visual-library/{ext_id}.json"
        title = art["title"]

        text = f"{art['title']}\n\nLocation: {art['location']}\nCulture: {art['culture']}\nRegion: {art['region']}\nDate: {art['date_label']}\n\n{art['description']}"
        checksum = hashlib.sha256(text.encode()).hexdigest()
        byte_size = len(text.encode("utf-8"))

        async with pool.acquire() as conn:
            existing = await conn.fetchval("SELECT id FROM raw_objects WHERE external_id = $1", ext_id)
            if existing:
                log.info("  SKIP (exists): %s", title)
                skipped += 1
                continue

            try:
                meta = json.dumps({"region": art["region"], "date_label": art["date_label"], "artifact_type": "visual_reference"})
                tsv_text = f"{title} {art['culture']} {art['location']} {art.get('region', '')} {art['description']}"

                async with conn.transaction():
                    ro_id = await conn.fetchval("""
                        INSERT INTO raw_objects (id, trusted_source_id, external_id, source_url,
                                                 content_type, checksum, byte_size, r2_key, fetched_at)
                        VALUES (gen_random_uuid(), $1, $2, $3, 'application/json', $4, $5, $6, NOW())
                        ON CONFLICT (r2_key) DO NOTHING RETURNING id
                    """, ts_id, ext_id, f"https://eden.internal/visual-library/{ext_id}",
                        checksum, byte_size, r2_key)
                    if not ro_id:
                        log.info("  SKIP (r2_key conflict): %s", title)
                        skipped += 1
                        continue

                    sr_id = await conn.fetchval("""
                        INSERT INTO source_records (id, raw_object_id, trusted_source_id, canonical_title,
                                                    culture, language_family, origin_place_name,
                                                    source_category, provenance_status, record_status,
                                                    metadata_jsonb, tsv, created_at, updated_at)
                        VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, 'site_archive',
                                'verified', 'published', $7::jsonb, to_tsvector('english', $8),
                                NOW(), NOW())
                        RETURNING id
                    """, ro_id, ts_id, title, art["culture"], art.get("region", ""),
                        art["location"], meta, tsv_text)

                    await conn.execute("""
                        INSERT INTO source_versions (id, source_record_id, version_type, language,
                                                     is_preferred, copyright_status, text_extracted,
                                                     tsv, created_at, updated_at)
                        VALUES (gen_random_uuid(), $1, 'museum_description', 'English',
                                true, 'public_domain', $2,
                                setweight(to_tsvector('english', $3), 'A') || to_tsvector('english', $2),
                                NOW(), NOW())
                    """, sr_id, text, title)

                    if art.get("date_start"):
                        await conn.execute("""
                            INSERT INTO source_dates (id, source_record_id, date_type, date_start, date_end,
                                                      date_label, dating_method, dating_confidence,
                                                      created_at, updated_at)
                            VALUES (gen_random_uuid(), $1, 'object_creation', $2, $3, $4,
                                    'archaeological', 'approximate', NOW(), NOW())
                        """, sr_id, art["date_start"], art.get("date_end", art["date_start"]),
                            art["date_label"])

                log.info("  OK: %s (%s)", title, art["date_label"])
                inserted += 1
            except Exception as e:
                log.error("  ERROR on %s: %s", title, e)
                errors += 1

    await pool.close()
    log.info("Done! Inserted: %d, Skipped: %d, Errors: %d", inserted, skipped, errors)


if __name__ == "__main__":
    asyncio.run(main())
