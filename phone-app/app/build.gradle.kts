plugins {
    id("com.android.application")
}

android {
    namespace = "dev.tarjim.phone"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.tarjim.phone"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.2.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
