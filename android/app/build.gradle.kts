// Vice Desk for Android: a native shell (WebView) around the same Python engine as the Windows app,
// run on the phone with Chaquopy. ffmpeg, ffprobe and QuickJS ship as static arm64 binaries in jniLibs
// (downloaded by the release workflow; see .github/workflows/release.yml).
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val viceVersion = Regex("""VERSION = "([^"]+)"""")
    .find(rootDir.resolve("../app/desk/core.py").readText())!!.groupValues[1]
val viceCode = viceVersion.split(".").let { it[0].toInt() * 10000 + it[1].toInt() * 100 + it[2].toInt() }

android {
    namespace = "com.claudegta6.vicedesk"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.claudegta6.vicedesk"
        minSdk = 29          // Android 10+: scoped storage, MediaStore without permissions
        targetSdk = 35
        versionCode = viceCode
        versionName = viceVersion
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    signingConfigs {
        // A stable key keeps updates installable over each other. Provide it through these env vars (CI secrets);
        // without them the build falls back to the debug key, and updates may need an uninstall first.
        create("release") {
            val ks = System.getenv("VICE_KEYSTORE")
            if (ks != null && file(ks).exists()) {
                storeFile = file(ks)
                storePassword = System.getenv("VICE_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("VICE_KEY_ALIAS")
                keyPassword = System.getenv("VICE_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (System.getenv("VICE_KEYSTORE") != null) signingConfigs.getByName("release")
                            else signingConfigs.getByName("debug")
        }
    }

    // Tools are executables named lib*.so so Android installs them in nativeLibraryDir, the one place an app may exec from.
    packaging { jniLibs { useLegacyPackaging = true } }

    sourceSets {
        getByName("main") { assets.srcDir(layout.buildDirectory.dir("generated/viceAssets")) }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            install("yt-dlp")
            install("yt-dlp-ejs")   // YouTube challenge solver scripts: without them YouTube hides every format
            install("requests")
            install("certifi")
            install("numpy")
            install("pysubs2")
            install("edge-tts")     // the free Microsoft voice (aiohttp and friends install as pure-Python wheels)
        }
    }
    sourceSets {
        getByName("main") { srcDir("../../app") }   // the desk package (server, task runner, Android entry)
    }
}

// Pipeline scripts and the UI are unpacked to real files on first start (runpy and the HTTP server need paths).
val copyViceBundle by tasks.registering(Sync::class) {
    from(rootDir.resolve("../scripts")) { into("bundle/scripts"); include("*.py", "fonts/**") }
    from(rootDir.resolve("../app/desk/ui")) { into("bundle/ui") }
    into(layout.buildDirectory.dir("generated/viceAssets"))
}
tasks.named("preBuild") { dependsOn(copyViceBundle) }
