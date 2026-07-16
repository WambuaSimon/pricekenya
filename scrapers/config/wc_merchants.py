"""Config for the WooCommerce-batch scraper.

Each entry is a merchant we auto-discovered as running a standard WooCommerce
theme with product-category URLs exposed in the site nav. Category URLs were
enumerated from each merchant's homepage on 2026-07-07 and mapped to
PriceKenya taxonomy leaves via slug keyword matching. When a merchant
customises their category slugs later, refresh this file with a re-discovery
pass rather than editing entries individually.

The batch scraper (scrapers/merchants/wc_batch.py) reads this dict and runs
each merchant sequentially through the shared fetch_woocommerce_category
helper — no per-merchant module needed.
"""

from __future__ import annotations

# merchant_slug → { meta: {...}, leaf_to_urls: { leaf: [url, ...] } }
WC_MERCHANTS: dict[str, dict] = {
    "fivestar-ke": {
        "meta": {"slug": "fivestar-ke", "name": "Fivestar Electronics", "base_url": "https://fivestar.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://fivestar.co.ke/product-category/accessories/headphones"],
            "blenders": ["https://fivestar.co.ke/product-category/kitchen-electronics/blender"],
            "cameras": ["https://fivestar.co.ke/product-category/cameras", "https://fivestar.co.ke/product-category/cameras/xiaomi-cameras"],
            "cooking": ["https://fivestar.co.ke/product-category/kitchen-electronics/cooker", "https://fivestar.co.ke/product-category/kitchen-electronics/microwaves"],
            "laptops": ["https://fivestar.co.ke/product-category/laptops", "https://fivestar.co.ke/product-category/laptops/lenovo-laptops"],
            "phone-tablet-accessories": ["https://fivestar.co.ke/product-category/accessories"],
            "phones": ["https://fivestar.co.ke/product-category/smartphones", "https://fivestar.co.ke/product-category/smartphones/mobile-phones"],
            "refrigerators": ["https://fivestar.co.ke/product-category/kitchen-electronics/chest-freezers", "https://fivestar.co.ke/product-category/kitchen-electronics/fridge", "https://fivestar.co.ke/product-category/kitchen-electronics/showcase-fridges"],
            "tablets": ["https://fivestar.co.ke/product-category/smartphones/kids-tablets", "https://fivestar.co.ke/product-category/smartphones/tablet"],
            "tvs": ["https://fivestar.co.ke/product-category/accessories/tv", "https://fivestar.co.ke/product-category/smart-tvs", "https://fivestar.co.ke/product-category/smart-tvs/samsung-smart-tvs"],
            "washers-dryers": ["https://fivestar.co.ke/product-category/dryers", "https://fivestar.co.ke/product-category/dryers/hisense-dryers", "https://fivestar.co.ke/product-category/dryers/samsung-dryers"],
        },
    },
    "le-ke": {
        "meta": {"slug": "le-ke", "name": "LE Kenya", "base_url": "https://le.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://le.co.ke/product-category/earphones-and-headphones"],
            "cooking": ["https://le.co.ke/product-category/home-appliances/cookers"],
            "laptops": ["https://le.co.ke/product-category/computers-laptops"],
            "phone-tablet-accessories": ["https://le.co.ke/product-category/cameras-accessories", "https://le.co.ke/product-category/electronic-accessories", "https://le.co.ke/product-category/electronic-accessories/accessories"],
            "refrigerators": ["https://le.co.ke/product-category/fridges-freezers"],
            "tablets": ["https://le.co.ke/product-category/phones-tablets"],
            "tvs": ["https://le.co.ke/product-category/smart-digital-tvs"],
        },
    },
    # finetech-ke moved to scrapers/merchants/finetech.py (WC Store API path).
    # Kept as `finetech-ke` target in ingest.py (not the wc-* prefix).
    "dixons-ke": {
        "meta": {"slug": "dixons-ke", "name": "Dixons", "base_url": "https://www.dixons.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://www.dixons.co.ke/product-category/mobiles/earphones-headphones"],
            "cameras": ["https://www.dixons.co.ke/product-category/cameras", "https://www.dixons.co.ke/product-category/cameras/digital-cameras", "https://www.dixons.co.ke/product-category/cameras/professional-cameras"],
            "cooking": ["https://www.dixons.co.ke/product-category/cookers-ovens/free-standing-cookers", "https://www.dixons.co.ke/product-category/cookers-ovens/microwave-ovens", "https://www.dixons.co.ke/product-category/cookers-ovens/ovens"],
            "laptops": ["https://www.dixons.co.ke/product-category/computing/laptops"],
            "phone-tablet-accessories": ["https://www.dixons.co.ke/product-category/electronics/accessories", "https://www.dixons.co.ke/product-category/fridges-freezers/accessories-fridges-freezers", "https://www.dixons.co.ke/product-category/kitchen-appliances/accessories-kitchen-appliances"],
            "phones": ["https://www.dixons.co.ke/product-category/mobiles/feature-phones", "https://www.dixons.co.ke/product-category/mobiles/smart-phones"],
            "refrigerators": ["https://www.dixons.co.ke/product-category/fridges-freezers", "https://www.dixons.co.ke/product-category/fridges-freezers/freezers", "https://www.dixons.co.ke/product-category/fridges-freezers/fridges"],
            "tablets": ["https://www.dixons.co.ke/product-category/mobiles/tablets"],
            "tvs": ["https://www.dixons.co.ke/product-category/electronics/televisions"],
            "washers-dryers": ["https://www.dixons.co.ke/product-category/washers-dryers/dishwasher", "https://www.dixons.co.ke/product-category/washers-dryers/dryers", "https://www.dixons.co.ke/product-category/washers-dryers/washing-machines"],
        },
    },
    "techonline-ke": {
        "meta": {"slug": "techonline-ke", "name": "TechOnline", "base_url": "https://techonline.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://techonline.co.ke/product-category/sound-system/party-speaker", "https://techonline.co.ke/product-category/sound-system/soundbar"],
            "blenders": ["https://techonline.co.ke/product-category/blenders"],
            "cameras": ["https://techonline.co.ke/product-category/accessories/cameras"],
            "cooking": ["https://techonline.co.ke/product-category/built-in-appliances/built-in-gas-hob", "https://techonline.co.ke/product-category/built-in-appliances/built-in-microwave", "https://techonline.co.ke/product-category/built-in-appliances/built-in-oven"],
            "ironing-laundry": ["https://techonline.co.ke/product-category/iron"],
            "phone-tablet-accessories": ["https://techonline.co.ke/product-category/accessories"],
            "refrigerators": ["https://techonline.co.ke/product-category/freezer", "https://techonline.co.ke/product-category/fridge"],
            "tvs": ["https://techonline.co.ke/product-category/smart-tvs", "https://techonline.co.ke/product-category/smart_tvs"],
            "washers-dryers": ["https://techonline.co.ke/product-category/dryer", "https://techonline.co.ke/product-category/washing-machines"],
        },
    },
    "jojabo-ke": {
        "meta": {"slug": "jojabo-ke", "name": "Jojabo Technologies", "base_url": "https://jojabotechnologies.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://jojabotechnologies.co.ke/product-category/audio-mixer", "https://jojabotechnologies.co.ke/product-category/bass-speakers", "https://jojabotechnologies.co.ke/product-category/earbuds"],
            "cameras": ["https://jojabotechnologies.co.ke/product-category/camera", "https://jojabotechnologies.co.ke/product-category/cctv-cameras"],
            "console-accessories": ["https://jojabotechnologies.co.ke/product-category/acoustics-gaming-headsets", "https://jojabotechnologies.co.ke/product-category/gaming-headsets"],
            "laptops": ["https://jojabotechnologies.co.ke/product-category/computer-accessories", "https://jojabotechnologies.co.ke/product-category/computer-accessories-laptops", "https://jojabotechnologies.co.ke/product-category/gaming-laptops"],
            "peripherals-accessories": ["https://jojabotechnologies.co.ke/product-category/gaming-keyboards", "https://jojabotechnologies.co.ke/product-category/keyboards", "https://jojabotechnologies.co.ke/product-category/mouse"],
            "phone-tablet-accessories": ["https://jojabotechnologies.co.ke/product-category/phone-accessories"],
            "phones": ["https://jojabotechnologies.co.ke/product-category/phones"],
            "tablets": ["https://jojabotechnologies.co.ke/product-category/deal-of-the-week-hot-sale-tablets", "https://jojabotechnologies.co.ke/product-category/ipad", "https://jojabotechnologies.co.ke/product-category/ipad-tablets"],
            "tvs": ["https://jojabotechnologies.co.ke/product-category/gaming-tv-sound-systems", "https://jojabotechnologies.co.ke/product-category/tv-sound-systems"],
        },
    },
    "tclke-ke": {
        "meta": {"slug": "tclke-ke", "name": "TCL Kenya", "base_url": "https://tclke.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://tclke.co.ke/product-category/jbl/jbl-earbuds", "https://tclke.co.ke/product-category/jbl/jbl-headphones", "https://tclke.co.ke/product-category/jbl/jbl-portable-speakers"],
            "cooking": ["https://tclke.co.ke/product-category/scl/scl-cookers"],
            "phone-tablet-accessories": ["https://tclke.co.ke/product-category/accessories"],
            "refrigerators": ["https://tclke.co.ke/product-category/scl/scl-freezers", "https://tclke.co.ke/product-category/scl/scl-fridges", "https://tclke.co.ke/product-category/tcl-refrigerators"],
            "tvs": ["https://tclke.co.ke/product-category/tcl-tvs", "https://tclke.co.ke/product-category/tcl-tvs/tcl-tvs-by-size", "https://tclke.co.ke/product-category/tcl-tvs/tv-by-feature"],
            "washers-dryers": ["https://tclke.co.ke/product-category/scl/scl-washing-machines", "https://tclke.co.ke/product-category/tcl-washing-machines", "https://tclke.co.ke/product-category/washing-machines"],
        },
    },
    "megatech-ke": {
        "meta": {"slug": "megatech-ke", "name": "Megatech Electronics", "base_url": "https://megatechelectronics.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://megatechelectronics.co.ke/product-category/audio", "https://megatechelectronics.co.ke/product-category/audio/earbuds-audio", "https://megatechelectronics.co.ke/product-category/audio/earphones"],
            "cameras": ["https://megatechelectronics.co.ke/product-category/cameras", "https://megatechelectronics.co.ke/product-category/cameras/insta-cameras"],
            "console-accessories": ["https://megatechelectronics.co.ke/product-category/gaming/controllers", "https://megatechelectronics.co.ke/product-category/gaming/accessories-gaming", "https://megatechelectronics.co.ke/product-category/gaming/headsets-gaming"],
            "phone-tablet-accessories": ["https://megatechelectronics.co.ke/product-category/accessories", "https://megatechelectronics.co.ke/product-category/accessories/car-chargers", "https://megatechelectronics.co.ke/product-category/accessories/chargers"],
            "phones": ["https://megatechelectronics.co.ke/product-category/audio/microphones", "https://megatechelectronics.co.ke/product-category/smartphones", "https://megatechelectronics.co.ke/product-category/smartphones/iphone"],
            "tablets": ["https://megatechelectronics.co.ke/product-category/tablets", "https://megatechelectronics.co.ke/product-category/tablets/infinix-tablet", "https://megatechelectronics.co.ke/product-category/tablets/oppo-tablets"],
        },
    },
    "zurimall-ke": {
        "meta": {"slug": "zurimall-ke", "name": "Zurimall", "base_url": "https://zurimall.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://zurimall.co.ke/product-category/tvs-hometheaters/soundbars"],
            "cameras": ["https://zurimall.co.ke/product-category/accessories/cameras", "https://zurimall.co.ke/product-category/accessories/cctv-cameras"],
            "laptops": ["https://zurimall.co.ke/product-category/all-laptops", "https://zurimall.co.ke/product-category/all-laptops-filters", "https://zurimall.co.ke/product-category/all-laptops-prices-filter", "https://zurimall.co.ke/product-category/accessories/gaming"],
            "phone-tablet-accessories": ["https://zurimall.co.ke/product-category/accessories", "https://zurimall.co.ke/product-category/accessories/networking-cables"],
            "phones": ["https://zurimall.co.ke/product-category/iphones", "https://zurimall.co.ke/product-category/phones", "https://zurimall.co.ke/product-category/phones/iphone"],
            "tvs": ["https://zurimall.co.ke/product-category/tvs-hometheaters", "https://zurimall.co.ke/product-category/tvs-hometheaters/hisense-tvs", "https://zurimall.co.ke/product-category/tvs-hometheaters/lg-tvs"],
        },
    },
    "pixels-ke": {
        "meta": {"slug": "pixels-ke", "name": "Pixels Electronics", "base_url": "https://pixelselectronics.co.ke"},
        "leaf_to_urls": {
            "cameras": ["https://pixelselectronics.co.ke/product-category/photo-video/cameras-drones"],
            "laptops": ["https://pixelselectronics.co.ke/product-category/computer-office", "https://pixelselectronics.co.ke/product-category/laptops-tablets-pcs/laptops", "https://pixelselectronics.co.ke/product-category/laptops/apple-macbook", "https://pixelselectronics.co.ke/product-category/laptops-tablets-pcs/laptops/gaming-laptop"],
            "phones": ["https://pixelselectronics.co.ke/product-category/cell-phones-accessories/cell-phones", "https://pixelselectronics.co.ke/product-category/smartphones", "https://pixelselectronics.co.ke/product-category/smartphones/mobile-phones"],
            "tablets": ["https://pixelselectronics.co.ke/product-category/laptops-tablets-pcs", "https://pixelselectronics.co.ke/product-category/laptops-tablets-pcs/tablets", "https://pixelselectronics.co.ke/product-category/tablets/apple-ipad"],
        },
    },
    "quest-ke": {
        "meta": {"slug": "quest-ke", "name": "Quest Appliances", "base_url": "https://www.questappliances.com"},
        "leaf_to_urls": {
            "audio": ["https://www.questappliances.com/product-category/televisions-audio/portable-speakers", "https://www.questappliances.com/product-category/televisions-audio/speakers-sound-systems"],
            "blenders": ["https://www.questappliances.com/product-category/home-appliances/blenders-juicers"],
            "cooking": ["https://www.questappliances.com/product-category/home-appliances/microwaves", "https://www.questappliances.com/product-category/home-appliances/pressure-cooker", "https://www.questappliances.com/product-category/home-appliances/standing-cookers"],
            "ironing-laundry": ["https://www.questappliances.com/product-category/home-appliances/garment-steamer", "https://www.questappliances.com/product-category/home-appliances/irons"],
            "kettles": ["https://www.questappliances.com/product-category/home-appliances/kettles"],
            "phone-tablet-accessories": ["https://www.questappliances.com/product-category/accessories", "https://www.questappliances.com/product-category/accessories/cables", "https://www.questappliances.com/product-category/personal-care/hair-accessories"],
            "phones": ["https://www.questappliances.com/product-category/smartphone"],
            "refrigerators": ["https://www.questappliances.com/product-category/home-appliances/refrigerators-freezers"],
            "tablets": ["https://www.questappliances.com/product-category/home-appliances/tabletop-cookers"],
            "toasters": ["https://www.questappliances.com/product-category/home-appliances/toasters-sandwich-makers"],
            "tvs": ["https://www.questappliances.com/product-category/televisions-audio", "https://www.questappliances.com/product-category/televisions-audio/cameras-televisions-audio", "https://www.questappliances.com/product-category/televisions-audio/digital-tvs"],
            "washers-dryers": ["https://www.questappliances.com/product-category/home-appliances/washing-machine"],
        },
    },
    "smartdevices-ke": {
        "meta": {"slug": "smartdevices-ke", "name": "Smart Devices Kenya", "base_url": "https://www.smartdeviceskenya.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://www.smartdeviceskenya.co.ke/product-category/audio", "https://www.smartdeviceskenya.co.ke/product-category/audio/soundbars", "https://www.smartdeviceskenya.co.ke/product-category/tv-audio"],
            "cooking": ["https://www.smartdeviceskenya.co.ke/product-category/home-appliances/cookers", "https://www.smartdeviceskenya.co.ke/product-category/home-appliances/microwaves"],
            "inverters": ["https://www.smartdeviceskenya.co.ke/product-category/inverters"],
            "solar-panels": ["https://www.smartdeviceskenya.co.ke/product-category/solar-panels"],
            "solar-batteries": ["https://www.smartdeviceskenya.co.ke/product-category/solar-batteries"],
            "laptops": ["https://www.smartdeviceskenya.co.ke/product-category/computers-printers/computer-desktops", "https://www.smartdeviceskenya.co.ke/product-category/computers-printers/laptops"],
            "phone-tablet-accessories": ["https://www.smartdeviceskenya.co.ke/product-category/power-banks"],
            "phones": ["https://www.smartdeviceskenya.co.ke/product-category/smartphones", "https://www.smartdeviceskenya.co.ke/product-category/smartphones/apple-iphones", "https://www.smartdeviceskenya.co.ke/product-category/smartphones/google-pixel-phones"],
            "refrigerators": ["https://www.smartdeviceskenya.co.ke/product-category/home-appliances/fridges"],
            "tablets": ["https://www.smartdeviceskenya.co.ke/product-category/laptops-tablets-pcs"],
            "tvs": ["https://www.smartdeviceskenya.co.ke/product-category/televisions"],
            "washers-dryers": ["https://www.smartdeviceskenya.co.ke/product-category/home-appliances/washing-machines"],
        },
    },
    "smartphoneskenya-ke": {
        "meta": {"slug": "smartphoneskenya-ke", "name": "Smartphones Kenya", "base_url": "https://smartphoneskenya.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://smartphoneskenya.co.ke/product-category/soundbar"],
            "laptops": ["https://smartphoneskenya.co.ke/product-category/computers", "https://smartphoneskenya.co.ke/product-category/computers/laptops"],
            "phone-tablet-accessories": ["https://smartphoneskenya.co.ke/product-category/phones-in-kenya/accessories-phones-in-kenya"],
            "phones": ["https://smartphoneskenya.co.ke/product-category/phones-in-kenya", "https://smartphoneskenya.co.ke/product-category/phones-in-kenya/infinix-phones", "https://smartphoneskenya.co.ke/product-category/phones-in-kenya/iphones"],
            "tablets": ["https://smartphoneskenya.co.ke/product-category/tablets-in-kenya/kids-tablets"],
            "tvs": ["https://smartphoneskenya.co.ke/product-category/televisions"],
        },
    },
    # patabay-ke removed: their custom WC theme hides prices from category
    # cards entirely — the price only renders on the product detail page.
    # The shared fetch_woocommerce_category helper works off the card, so
    # every listing dropped for lack of a .price element. Bringing this
    # merchant online would need a per-product-page fetcher (Hotpoint style).
    "zuka-ke": {
        "meta": {"slug": "zuka-ke", "name": "Zuka Electronics", "base_url": "https://zuka.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://zuka.co.ke/product-category/sound-systems/bluetooth-speakers"],
            "blenders": ["https://zuka.co.ke/product-category/blenders"],
            "cooking": ["https://zuka.co.ke/product-category/cookers", "https://zuka.co.ke/product-category/hobs", "https://zuka.co.ke/product-category/in-built-cookers"],
            "phone-tablet-accessories": ["https://zuka.co.ke/product-category/accessories"],
            "phones": ["https://zuka.co.ke/product-category/mobile-phones"],
            # showcase-chillers is a display fridge category despite the "case" substring
            # tripping the accessories keyword — route to refrigerators.
            "refrigerators": ["https://zuka.co.ke/product-category/freezer", "https://zuka.co.ke/product-category/showcase-chillers"],
            "tvs": ["https://zuka.co.ke/product-category/televisions"],
            "washers-dryers": ["https://zuka.co.ke/product-category/washing-machines"],
        },
    },
    # techstore-ke moved to scrapers/merchants/techstore.py (WC Store API path).
    "devicestech-ke": {
        "meta": {"slug": "devicestech-ke", "name": "Devices Technology Store", "base_url": "https://www.devicestech.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://www.devicestech.co.ke/product-category/computer-accessories/audio-speakers", "https://www.devicestech.co.ke/product-category/computer-accessories/earphones", "https://www.devicestech.co.ke/product-category/computer-accessories/headphones"],
            "cameras": ["https://www.devicestech.co.ke/product-category/cctv-cameras/hd-cameras", "https://www.devicestech.co.ke/product-category/cctv-cameras/ip-cameras"],
            "laptops": ["https://www.devicestech.co.ke/product-category/computer-accessories/docking-stations-computer-accessories"],
            "peripherals-accessories": ["https://www.devicestech.co.ke/product-category/computer-accessories/keyboards", "https://www.devicestech.co.ke/product-category/computer-accessories/mouse", "https://www.devicestech.co.ke/product-category/computer-accessories/usb-hub"],
            "phone-tablet-accessories": ["https://www.devicestech.co.ke/product-category/computer-accessories/cables", "https://www.devicestech.co.ke/product-category/computer-accessories/laptop-chargers"],
            "tablets": ["https://www.devicestech.co.ke/product-category/tablets"],
            "tvs": ["https://www.devicestech.co.ke/product-category/tvs"],
        },
    },
    "nairobilaptops-ke": {
        "meta": {"slug": "nairobilaptops-ke", "name": "Nairobi Laptops", "base_url": "https://nairobilaptops.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://nairobilaptops.co.ke/product-category/soundbars"],
            "cameras": ["https://nairobilaptops.co.ke/product-category/camera", "https://nairobilaptops.co.ke/product-category/cctv"],
            "laptops": ["https://nairobilaptops.co.ke/product-category/desktops", "https://nairobilaptops.co.ke/product-category/laptops"],
            "phones": ["https://nairobilaptops.co.ke/product-category/phones"],
            "tvs": ["https://nairobilaptops.co.ke/product-category/televisions"],
        },
    },
    "solarshop-ke": {
        "meta": {"slug": "solarshop-ke", "name": "SolarShop Africa", "base_url": "https://solarshop.co.ke"},
        # Solar-focused specialist. Dropping /solar-charge-controllers/ URLs
        # (my keyword discovery routed them to console-accessories because
        # "controller" is in the leaf keyword — that's for PS5/Xbox pads,
        # not power electronics; no matcher covers charge controllers yet).
        # Also dropping /solar-dc-cables-accessories/ and outdoor-lights.
        "leaf_to_urls": {
            "inverters": ["https://solarshop.co.ke/product-category/solar-inverters"],
            "solar-batteries": ["https://solarshop.co.ke/product-category/solar-batteries", "https://solarshop.co.ke/product-category/solar-batteries/lithium-ion-batteries"],
        },
    },
    "solarstore-ke": {
        "meta": {"slug": "solarstore-ke", "name": "Solar Store East Africa", "base_url": "https://solarstore.co.ke"},
        "leaf_to_urls": {
            "inverters": ["https://solarstore.co.ke/product-category/solar-inverters", "https://solarstore.co.ke/product-category/solar-inverters/hybrid-inverters"],
        },
    },
    # sollatek-ke moved to shopify_merchants.py — their store is Shopify at
    # shop.sollatek.com, not WooCommerce at sollatek.co.ke (which is the
    # corporate marketing site).
    # audiocom-ke moved to scrapers/merchants/audiocom.py (WC Store API).
    "camerastore-ke": {
        "meta": {"slug": "camerastore-ke", "name": "Camera Store Kenya", "base_url": "https://camerastoreke.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://camerastoreke.co.ke/product-category/headphones", "https://camerastoreke.co.ke/product-category/headphones/boya-headphones", "https://camerastoreke.co.ke/product-category/headphones/maono-headphones"],
            "cameras": ["https://camerastoreke.co.ke/product-category/camera-lens/canon-camera-lens", "https://camerastoreke.co.ke/product-category/camera-lens/nikon-camera-lens", "https://camerastoreke.co.ke/product-category/camera-lens/sony-camera-lens"],
        },
    },
    "eamobitech-ke": {
        "meta": {"slug": "eamobitech-ke", "name": "EAM Mobitech", "base_url": "https://eamobitech.com"},
        "leaf_to_urls": {
            "audio": ["https://eamobitech.com/product-category/audio-podcast", "https://eamobitech.com/product-category/audio-podcast/dynamic-microphones"],
            "cameras": ["https://eamobitech.com/product-category/camera-video", "https://eamobitech.com/product-category/camera-video-accessories"],
            "laptops": ["https://eamobitech.com/product-category/apple-store/macbook", "https://eamobitech.com/product-category/computers"],
            "peripherals-accessories": ["https://eamobitech.com/product-category/computers/keyboards-mice", "https://eamobitech.com/product-category/computers/webcams-accessories"],
            "phones": ["https://eamobitech.com/product-category/apple-store/iphones", "https://eamobitech.com/product-category/smartphones-tablets"],
            "tablets": ["https://eamobitech.com/product-category/apple-store/ipads"],
            "tvs": ["https://eamobitech.com/product-category/tvs-and-hometheatres", "https://eamobitech.com/product-category/tvs-entertainment"],
        },
    },
    "housewife-ke": {
        "meta": {"slug": "housewife-ke", "name": "Housewife's Paradise", "base_url": "https://housewifesparadise.com"},
        "leaf_to_urls": {
            "audio": ["https://housewifesparadise.com/product-category/bluetooth-speakers"],
            "blenders": ["https://housewifesparadise.com/product-category/small-domestic-appliances/blenders", "https://housewifesparadise.com/product-category/small-domestic-appliances/hand-mixers", "https://housewifesparadise.com/product-category/small-domestic-appliances/juicers"],
            "cooking": ["https://housewifesparadise.com/product-category/cookers", "https://housewifesparadise.com/product-category/cookers/samsung-cookers", "https://housewifesparadise.com/product-category/cookers/scl-cookers"],
            "ironing-laundry": ["https://housewifesparadise.com/product-category/small-domestic-appliances/garment-steamers", "https://housewifesparadise.com/product-category/small-domestic-appliances/iron-boxes"],
            "kettles": ["https://housewifesparadise.com/product-category/small-domestic-appliances/kettles"],
            "phones": ["https://housewifesparadise.com/product-category/mobile-phones"],
            "refrigerators": ["https://housewifesparadise.com/product-category/refrigerators-freezers", "https://housewifesparadise.com/product-category/refrigerators-freezers/lg-bottom-mount-refrigerators"],
            "toasters": ["https://housewifesparadise.com/product-category/small-domestic-appliances/sandwich-makers", "https://housewifesparadise.com/product-category/small-domestic-appliances/toasters"],
            "tvs": ["https://housewifesparadise.com/product-category/tvs"],
            "washers-dryers": ["https://housewifesparadise.com/product-category/home-appliances/lg-dishwashers", "https://housewifesparadise.com/product-category/washing-machines"],
        },
    },
    "armco-ke": {
        "meta": {"slug": "armco-ke", "name": "Armco Kenya", "base_url": "https://armcokenya.com"},
        "leaf_to_urls": {
            "audio": ["https://armcokenya.com/product-category/home-entertainment/soundbars-and-boom-boxes-kenya"],
            "blenders": ["https://armcokenya.com/product-category/kitchen-appliances/blenders", "https://armcokenya.com/product-category/kitchen-appliances/food-processors", "https://armcokenya.com/product-category/kitchen-appliances/hand-mixers"],
            "cooking": ["https://armcokenya.com/product-category/kitchen-appliances/microwaves", "https://armcokenya.com/product-category/kitchen-appliances/portable-cookers", "https://armcokenya.com/product-category/kitchen-appliances/table-top-cooker"],
            "ironing-laundry": ["https://armcokenya.com/product-category/small-appliances/irons"],
            "kettles": ["https://armcokenya.com/product-category/kitchen-appliances/kettles", "https://armcokenya.com/product-category/small-appliances/kettles"],
            "refrigerators": ["https://armcokenya.com/product-category/large-appliances/chest-freezers", "https://armcokenya.com/product-category/large-appliances/refrigerators"],
            "toasters": ["https://armcokenya.com/product-category/kitchen-appliances/toaster"],
            "tvs": ["https://armcokenya.com/product-category/home-entertainment/televisions"],
            "washers-dryers": ["https://armcokenya.com/product-category/large-appliances/dryer", "https://armcokenya.com/product-category/large-appliances/washing-machines"],
        },
    },
    # newmatic-ke moved to scrapers/merchants/newmatic.py (WC Store API path).
    "nextbuy-ke": {
        "meta": {"slug": "nextbuy-ke", "name": "NextBuy Kenya", "base_url": "https://nextbuy.co.ke"},
        "leaf_to_urls": {
            "phones": ["https://nextbuy.co.ke/product-category/phones-tablets/smartphones", "https://nextbuy.co.ke/product-category/like-new-electronics/certified-pre-owned-iphones", "https://nextbuy.co.ke/product-category/like-new-electronics/used-samsung-phones"],
        },
    },
    # pricepoint-ke moved to scrapers/merchants/pricepoint.py (WC Store API).
    "phoneshop-ke": {
        "meta": {"slug": "phoneshop-ke", "name": "Phone Shop Kenya", "base_url": "https://phoneshopkenya.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://phoneshopkenya.co.ke/product-category/headphones"],
            "cameras": ["https://phoneshopkenya.co.ke/product-category/content-creator-kit/cameras", "https://phoneshopkenya.co.ke/product-category/insta-360-cameras"],
            "console-accessories": ["https://phoneshopkenya.co.ke/product-category/gaming-controllers", "https://phoneshopkenya.co.ke/product-category/gaming-headsets-2", "https://phoneshopkenya.co.ke/product-category/headphones/gaming-headsets"],
            "laptops": ["https://phoneshopkenya.co.ke/product-category/macbook"],
            "phone-tablet-accessories": ["https://phoneshopkenya.co.ke/product-category/accessories", "https://phoneshopkenya.co.ke/product-category/mobile-accessories"],
            "phones": ["https://phoneshopkenya.co.ke/product-category/apple-phones", "https://phoneshopkenya.co.ke/product-category/asus-phones", "https://phoneshopkenya.co.ke/product-category/blackview-phones"],
            "tablets": ["https://phoneshopkenya.co.ke/product-category/apple-ipad", "https://phoneshopkenya.co.ke/product-category/amazon-tablets", "https://phoneshopkenya.co.ke/product-category/galaxy-tablet"],
        },
    },
    # bestbuyy-ke and tdk-ke deferred: their category pages trigger a
    # stronger Cloudflare Turnstile than their homepages did, so Playwright
    # hits the challenge repeatedly, exhausts retries, and blows the job
    # timeout for a batch fetch. Bringing them online would need either
    # residential-proxy Playwright or a per-URL warm-up phase; neither is
    # worth the cost right now given the categories they cover already have
    # heavy coverage from Jumia/Kilimall/Hotpoint/etc.
    "overtech-ke": {
        "meta": {"slug": "overtech-ke", "name": "Overtech Kenya", "base_url": "https://overtech.co.ke"},
        "client_type": "playwright",  # Cloudflare Turnstile — plain httpx returns 403
        "leaf_to_urls": {
            "audio": ["https://overtech.co.ke/product-category/audio-systems/earphones-headphones", "https://overtech.co.ke/product-category/audio-systems/portable-speakers", "https://overtech.co.ke/product-category/audio-systems/soundbars"],
            "cameras": ["https://overtech.co.ke/product-category/cameras", "https://overtech.co.ke/product-category/cameras/photography"],
            "console-accessories": ["https://overtech.co.ke/product-category/gaming/gaming-accessories"],
            "laptops": ["https://overtech.co.ke/product-category/computing/laptops", "https://overtech.co.ke/product-category/computing/computer-desktops"],
            "peripherals-accessories": ["https://overtech.co.ke/product-category/computing/computer-accessories"],
            "phone-tablet-accessories": ["https://overtech.co.ke/product-category/mobile-accessories/chargers-cables", "https://overtech.co.ke/product-category/mobile-accessories/memory-cards"],
        },
    },
    "hisense-kenya-ke": {
        "meta": {"slug": "hisense-kenya-ke", "name": "Hisense Kenya (Official)", "base_url": "https://hisense-kenya.co.ke"},
        # Cloudflare + Turnstile JS challenge; plain httpx and curl_cffi both
        # get 403. Playwright headless Chromium executes the challenge JS
        # cleanly here (checked on 2026-07-13). Newer Turnstile variants
        # detect plain headless via navigator.webdriver etc. — if a shielded
        # merchant stays at 403 after switching to playwright, add stealth.
        "client_type": "playwright",
        "leaf_to_urls": {
            "audio": ["https://hisense-kenya.co.ke/product-category/soundbars"],
            "cooking": ["https://hisense-kenya.co.ke/product-category/cookers-ovens", "https://hisense-kenya.co.ke/product-category/microwaves"],
            "refrigerators": ["https://hisense-kenya.co.ke/product-category/fridges-freezers"],
            "tvs": ["https://hisense-kenya.co.ke/product-category/tvs", "https://hisense-kenya.co.ke/product-category/tvs/qled-4k", "https://hisense-kenya.co.ke/product-category/tvs/uhd-4k"],
            "washers-dryers": ["https://hisense-kenya.co.ke/product-category/washing-machines"],
        },
    },
    "nairobitvshop-ke": {
        "meta": {"slug": "nairobitvshop-ke", "name": "Nairobi TV Shop", "base_url": "https://nairobitvshop.co.ke"},
        "leaf_to_urls": {
            "audio": ["https://nairobitvshop.co.ke/product-category/headphones", "https://nairobitvshop.co.ke/product-category/portable-speakers", "https://nairobitvshop.co.ke/product-category/soundbars"],
            "laptops": ["https://nairobitvshop.co.ke/product-category/laptops-desktops"],
            "phone-tablet-accessories": ["https://nairobitvshop.co.ke/product-category/accessories"],
            "tvs": ["https://nairobitvshop.co.ke/product-category/television", "https://nairobitvshop.co.ke/product-category/tv-mounts"],
        },
    },
}
